"""Vista de mapa (OpenStreetMap vía Leaflet) para geolocalizar vídeos."""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .. import tools
from ..catalog import Video
from .grid import VIDEO_ID_MIME


class _Bridge(QObject):
    marker_clicked = Signal(int)

    @Slot(int)
    def markerClicked(self, video_id: int) -> None:
        self.marker_clicked.emit(video_id)


class _MapWebView(QWebEngineView):
    """Subclase para poder aceptar drops: los eventos de drag&drop sobre un
    QWebEngineView los recibe la propia vista, no el widget contenedor."""

    videos_dropped = Signal(list, float, float)  # ids, x, y (px, relativos a la vista)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        # map.html se carga como file://: por defecto QtWebEngine no deja que ese
        # origen pida recursos remotos (las tiles de OSM/CARTO se quedarían en negro).
        self.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(VIDEO_ID_MIME):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(VIDEO_ID_MIME):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        raw = e.mimeData().data(VIDEO_ID_MIME)
        if not raw:
            super().dropEvent(e)
            return
        ids = [int(s) for s in bytes(raw).decode("ascii").split(",") if s]
        if ids:
            pos = e.position()
            self.videos_dropped.emit(ids, pos.x(), pos.y())
        e.acceptProposedAction()


class MapView(QWidget):
    """Mapa OSM con los vídeos geolocalizados del filtro actual; soltar ahí un
    vídeo arrastrado desde la cuadrícula le asigna esa ubicación."""

    marker_clicked = Signal(int)
    location_dropped = Signal(list, float, float)  # ids, lat, lon

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = _MapWebView(self)
        self.view.videos_dropped.connect(self._on_dropped)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

        self._bridge = _Bridge(self)
        self._bridge.marker_clicked.connect(self.marker_clicked)
        self._channel = QWebChannel(self)
        self._channel.registerObject("bridge", self._bridge)
        self.view.page().setWebChannel(self._channel)

        self._loaded = False
        self._pending_videos: list[Video] = []
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.load(QUrl.fromLocalFile(str(tools.webres_dir() / "map.html")))

    def _on_load_finished(self, ok: bool) -> None:
        self._loaded = ok
        if ok:
            self._push_markers()

    def set_videos(self, videos: list[Video]) -> None:
        self._pending_videos = [v for v in videos if v.has_gps]
        if self._loaded:
            self._push_markers()

    def fit_to_markers(self) -> None:
        """Encuadra el mapa a los pines actuales. Llamar solo al entrar en la vista
        (no en cada refresco), o se le movería el mapa al usuario bajo el ratón."""
        if self._loaded:
            self.view.page().runJavaScript("fitMarkers();")

    def _push_markers(self) -> None:
        data = [
            {"id": v.id, "lat": v.row["lat"], "lon": v.row["lon"], "filename": v.filename}
            for v in self._pending_videos
        ]
        self.view.page().runJavaScript(f"setMarkers({json.dumps(data)});")

    def highlight(self, video_id: int) -> None:
        if self._loaded:
            self.view.page().runJavaScript(f"highlightMarker({video_id});")

    def _on_dropped(self, ids: list, x: float, y: float) -> None:
        def on_result(res: str) -> None:
            if not res:
                return
            ll = json.loads(res)
            self.location_dropped.emit(ids, ll["lat"], ll["lon"])

        self.view.page().runJavaScript(f"containerPointToLatLng({x}, {y})", on_result)
