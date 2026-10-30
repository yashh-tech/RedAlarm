import os

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.graphics import Color, Rectangle
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.widget import Widget

class LoadingBar(Widget):
    progress = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        with self.canvas:
            # Dark grey track
            Color(0.18, 0.18, 0.18, 1)
            self.track = Rectangle(
                pos=self.pos,
                size=self.size
            )

            # Red loading fill
            Color(1, 0.12, 0.16, 1)
            self.fill = Rectangle(
                pos=self.pos,
                size=(0, self.height)
            )

        self.bind(
            pos=self.update_bar,
            size=self.update_bar,
            progress=self.update_bar
        )

    def update_bar(self, *args):
        self.track.pos = self.pos
        self.track.size = self.size

        self.fill.pos = self.pos
        self.fill.size = (
            self.width * self.progress / 100,
            self.height
        )


class SplashScreen(FloatLayout):
    def __init__(self, duration=1, **kwargs):
        super().__init__(**kwargs)

        self.duration = duration
        self.elapsed = 0

        # Pure black background
        with self.canvas.before:
            Color(0, 0, 0, 1)
            self.bg = Rectangle(
                pos=self.pos,
                size=self.size
            )

        self.bind(pos=self.update_bg, size=self.update_bg)

        # Centered splash content
               # Centered RedAlarm splash content
        content = BoxLayout(
            orientation="vertical",
            spacing=dp(10),
            size_hint=(0.86, None),
            height=dp(315),
            pos_hint={
                "center_x": 0.5,
                "center_y": 0.5
            }
        )

        # RedAlarm clock logo
        logo_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "splashimage.png"
        )

        content.add_widget(
            Image(
                source=logo_path,
                size_hint=(1, None),
                height=dp(150),
                allow_stretch=True,
                keep_ratio=True
            )
        )

        # Large RedAlarm wordmark
        content.add_widget(
            Label(
                text="[color=#FF1F29]Red[/color][color=#FFFFFF]Alarm[/color]",
                markup=True,
                font_size="44sp",
                bold=True,
                size_hint=(1, None),
                height=dp(58)
            )
        )

        content.add_widget(
            Label(
                text="Your time. Your control.",
                font_size="16sp",
                color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=dp(28)
            )
        )

        self.loading_bar = LoadingBar(
            size_hint=(1, None),
            height=dp(6)
        )
        content.add_widget(self.loading_bar)

        self.loading_text = Label(
            text="Loading... 0%",
            font_size="13sp",
            color=(0.7, 0.7, 0.7, 1),
            size_hint=(1, None),
            height=dp(22)
        )
        content.add_widget(self.loading_text)

        self.add_widget(content)
        # Fill the bar over the one-second splash duration
        self._loading_event = Clock.schedule_interval(
            self.update_loading,
            1 / 60
        )

    def clear_startup_error(self):
        for name in ("_startup_error_detail", "_startup_retry_button"):
            widget = getattr(self, name, None)
            if widget is not None and widget.parent is not None:
                widget.parent.remove_widget(widget)
            setattr(self, name, None)
        self.loading_text.text = "Loading... 0%"
        self.loading_text.color = (0.7, 0.7, 0.7, 1)
        self.elapsed = 0
        self.loading_bar.progress = 0

    def show_startup_error(self, message, retry_callback=None):
        self.clear_startup_error()
        self.loading_text.text = "STARTUP NEEDS ATTENTION"
        self.loading_text.color = (1, 0.25, 0.3, 1)
        self._startup_error_detail = Label(
            text=str(message)[:220],
            color=(0.9, 0.9, 0.9, 1),
            font_size="12sp",
            halign="center",
            valign="middle",
            size_hint=(0.9, None),
            height=dp(86),
            pos_hint={"center_x": 0.5, "center_y": 0.22},
        )
        self._startup_error_detail.bind(
            size=lambda widget, value: setattr(widget, "text_size", value)
        )
        self.add_widget(self._startup_error_detail)
        if retry_callback is not None:
            self._startup_retry_button = Button(
                text="RETRY STARTUP",
                size_hint=(0.62, None),
                height=dp(46),
                pos_hint={"center_x": 0.5, "y": 0.055},
                background_normal="",
                background_color=(0.62, 0.025, 0.06, 1),
                color=(1, 1, 1, 1),
            )
            self._startup_retry_button.bind(on_release=lambda *_: retry_callback())
            self.add_widget(self._startup_retry_button)

    def update_bg(self, *args):
        self.bg.pos = self.pos
        self.bg.size = self.size

    def update_loading(self, dt):
        self.elapsed += dt

        percentage = min(
            100,
            (self.elapsed / self.duration) * 100
        )

        self.loading_bar.progress = percentage
        self.loading_text.text = (
            f"Loading... {int(percentage)}%"
        )

        if percentage >= 100:
            self.loading_text.text = "Opening RedAlarm..."
            return False

    def on_parent(self, instance, parent):
        if parent is None:
            if hasattr(self, "_loading_event"):
                self._loading_event.cancel()


def add_splash_screen(app_root, duration=1):
    wrapper = FloatLayout()

    app_root.size_hint = (1, 1)
    wrapper.add_widget(app_root)

    splash = SplashScreen(duration=duration)
    wrapper.add_widget(splash)

    def hide_splash(dt):
        if splash.parent is wrapper:
            wrapper.remove_widget(splash)

    Clock.schedule_once(hide_splash, duration)

    return wrapper


# Standalone preview in Visual Studio
if __name__ == "__main__":

    class SplashPreviewApp(App):
        def build(self):
            return SplashScreen(duration=1)

    SplashPreviewApp().run()
