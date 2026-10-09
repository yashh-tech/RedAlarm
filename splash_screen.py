
from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.graphics import Color, Rectangle
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
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
    def __init__(self, duration=3, **kwargs):
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
        content = BoxLayout(
            orientation="vertical",
            spacing=dp(14),
            size_hint=(0.82, 0.35),
            pos_hint={
                "center_x": 0.5,
                "center_y": 0.5
            }
        )

        content.add_widget(
             Label(
             text="[color=#FF1F29]Red[/color][color=#FFFFFF]Alarm[/color]",
             markup=True,
             font_size="34sp",
             bold=True
            )
        )

        content.add_widget(
            Label(
                text="Your time. Your control.",
                font_size="16sp",
                color=(1, 1, 1, 1)
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

        # Fill the bar over 3 seconds
        self._loading_event = Clock.schedule_interval(
            self.update_loading,
            1 / 60
        )

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
            self.loading_text.text = "Ready!"
            return False

    def on_parent(self, instance, parent):
        if parent is None:
            if hasattr(self, "_loading_event"):
                self._loading_event.cancel()


def add_splash_screen(app_root, duration=3):
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
            return SplashScreen(duration=3)

    SplashPreviewApp().run()
