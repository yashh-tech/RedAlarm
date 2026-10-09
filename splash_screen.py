
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.graphics import Color, Rectangle
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label


class SplashScreen(FloatLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Dark background
        with self.canvas.before:
            Color(0.07, 0.07, 0.11, 1)
            self.bg = Rectangle(
                pos=self.pos,
                size=self.size
            )

        self.bind(pos=self.update_bg, size=self.update_bg)

        # Text in the center
        content = BoxLayout(
            orientation="vertical",
            spacing=dp(12),
            size_hint=(0.9, 0.3),
            pos_hint={"center_x": 0.5, "center_y": 0.5}
        )

        content.add_widget(
            Label(
                text="RedAlarm",
                font_size="34sp",
                bold=True,
                color=(1, 0.25, 0.25, 1)
            )
        )

        content.add_widget(
            Label(
                text="Your time. Your control.",
                font_size="16sp",
                color=(1, 1, 1, 1)
            )
        )

        self.add_widget(content)

    def update_bg(self, *args):
        self.bg.pos = self.pos
        self.bg.size = self.size


def add_splash_screen(app_root, duration=2):
    # Keep the existing app underneath the splash.
    wrapper = FloatLayout()
    app_root.size_hint = (1, 1)
    wrapper.add_widget(app_root)

    splash = SplashScreen()
    wrapper.add_widget(splash)

    def hide_splash(dt):
        if splash.parent is wrapper:
            wrapper.remove_widget(splash)

    Clock.schedule_once(hide_splash, duration)

    return wrapper
