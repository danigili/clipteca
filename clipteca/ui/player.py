"""Reproductor: libmpv si está disponible (HDR, HEVC, búsqueda exacta); si no, QtMultimedia."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget


class PlayerBase(QWidget):
    position_changed = Signal(float)
    duration_changed = Signal(float)
    playing_changed = Signal(bool)
    backend = "?"

    def load(self, path: str, start: float = 0.0): ...
    def unload(self): ...
    def set_rotation(self, degrees: int): ...
    def play_pause(self): ...
    def play(self): ...
    def pause(self): ...
    def seek(self, t: float): ...
    def step(self, frames: int): ...
    def position(self) -> float: return 0.0
    def is_playing(self) -> bool: return False
    def shutdown(self): ...


class MpvPlayer(PlayerBase):
    backend = "mpv"

    def __init__(self, parent=None):
        super().__init__(parent)
        import mpv  # noqa: F401  (lanza excepción si falta libmpv)

        self.video = QWidget(self)
        self.video.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self.video.setAttribute(Qt.WA_NativeWindow)
        self.video.setFocusPolicy(Qt.NoFocus)
        self.video.setStyleSheet("background:#000")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.video)
        self.mpv = mpv.MPV(
            wid=str(int(self.video.winId())),
            vo="gpu", hwdec="auto-safe", keep_open="yes", idle="yes", osc="no",
            input_default_bindings=False, input_vo_keyboard=False, input_cursor=False,
            hr_seek="yes", pause=True, loglevel="error", cursor_autohide="no",
        )
        self._pos = 0.0
        self._dur = 0.0
        self._playing = False
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _poll(self):
        try:
            pos = self.mpv.time_pos
            dur = self.mpv.duration
            paused = self.mpv.pause
        except Exception:  # noqa: BLE001
            return
        if dur is not None and abs(dur - self._dur) > 1e-3:
            self._dur = dur
            self.duration_changed.emit(dur)
        if pos is not None and abs(pos - self._pos) > 1e-4:
            self._pos = pos
            self.position_changed.emit(pos)
        playing = not paused if paused is not None else False
        if playing != self._playing:
            self._playing = playing
            self.playing_changed.emit(playing)

    def load(self, path, start=0.0):
        self._dur = 0.0
        self.mpv.pause = True
        self.mpv.loadfile(path, start=f"{start:.3f}")

    def unload(self):
        self.mpv.command("stop")

    def set_rotation(self, degrees: int):
        self.mpv.video_rotate = degrees % 360

    def play_pause(self):
        self.mpv.pause = not self.mpv.pause

    def play(self):
        self.mpv.pause = False

    def pause(self):
        self.mpv.pause = True

    def seek(self, t):
        try:
            self.mpv.seek(max(0.0, t), reference="absolute", precision="exact")
        except Exception:  # noqa: BLE001
            pass

    def step(self, frames):
        self.mpv.pause = True
        for _ in range(abs(frames)):
            self.mpv.command("frame-step" if frames > 0 else "frame-back-step")

    def position(self):
        return self._pos

    def is_playing(self):
        return self._playing

    def shutdown(self):
        self.timer.stop()
        try:
            self.mpv.terminate()
        except Exception:  # noqa: BLE001
            pass


class QtPlayer(PlayerBase):
    backend = "QtMultimedia"

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget

        self.view = QVideoWidget(self)
        self.view.setFocusPolicy(Qt.NoFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)
        self.audio = QAudioOutput(self)
        self.p = QMediaPlayer(self)
        self.p.setAudioOutput(self.audio)
        self.p.setVideoOutput(self.view)
        self._start = 0.0
        self._fps = 30.0
        self.p.positionChanged.connect(lambda ms: self.position_changed.emit(ms / 1000))
        self.p.durationChanged.connect(lambda ms: self.duration_changed.emit(ms / 1000))
        self.p.playbackStateChanged.connect(
            lambda s: self.playing_changed.emit(s == QMediaPlayer.PlayingState))
        self.p.mediaStatusChanged.connect(self._status)

    def _status(self, st):
        from PySide6.QtMultimedia import QMediaPlayer
        if st == QMediaPlayer.LoadedMedia and self._start:
            self.p.setPosition(int(self._start * 1000))
            self._start = 0.0

    def load(self, path, start=0.0):
        self._start = start
        self.p.setSource(QUrl.fromLocalFile(path))
        self.p.pause()

    def unload(self):
        self.p.stop()
        self.p.setSource(QUrl())

    def play_pause(self):
        self.pause() if self.is_playing() else self.play()

    def play(self):
        self.p.play()

    def pause(self):
        self.p.pause()

    def seek(self, t):
        self.p.setPosition(int(max(0.0, t) * 1000))

    def step(self, frames):
        self.p.pause()
        self.seek(self.position() + frames / self._fps)

    def set_fps(self, fps):
        self._fps = fps or 30.0

    def position(self):
        return self.p.position() / 1000

    def is_playing(self):
        from PySide6.QtMultimedia import QMediaPlayer
        return self.p.playbackState() == QMediaPlayer.PlayingState

    def shutdown(self):
        self.p.stop()


def create_player(parent=None) -> PlayerBase:
    try:
        return MpvPlayer(parent)
    except Exception as e:  # noqa: BLE001
        print(f"libmpv no disponible ({e}); usando QtMultimedia")
        return QtPlayer(parent)
