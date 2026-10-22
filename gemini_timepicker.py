from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.recycleview import RecycleView
from kivy.uix.label import Label
from kivy.properties import StringProperty, BooleanProperty
from kivy.lang import Builder
from kivy.clock import Clock

KV = '''
<WheelItem>:
    text: root.text
    font_size: '24sp'
    color: (1, 1, 1, 0.95) if root.is_selected else (1, 1, 1, 0.3)
    bold: root.is_selected
    size_hint_y: None
    height: '50dp'
    halign: 'center'
    valign: 'middle'

<SmoothWheelView>:
    viewclass: 'WheelItem'
    effect_cls: 'ScrollEffect'
    scroll_type: ['bars', 'content']
    bar_width: 0
    
    RecycleBoxLayout:
        id: rbl
        default_size: None, '50dp'
        default_size_hint: 1, None
        size_hint_y: None
        height: self.minimum_height
        orientation: 'vertical'
        padding: [0, 110, 0, 110]

<AlarmPickerUI>:
    orientation: 'vertical'
    canvas.before:
        Color:
            rgba: 0.05, 0.05, 0.05, 1
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        orientation: 'vertical'
        size_hint: 0.92, 0.88
        pos_hint: {'center_x': 0.5, 'center_y': 0.5}
        padding: '24dp'
        spacing: '15dp'
        canvas.before:
            Color:
                rgba: 0.11, 0.11, 0.11, 1
            RoundedRectangle:
                pos: self.pos
                size: self.size
                radius: [28,]

        BoxLayout:
            orientation: 'vertical'
            size_hint_y: None
            height: '75dp'
            spacing: '6dp'

            Label:
                text: 'SET ALARM'
                font_size: '12sp'
                color: 0.55, 0.55, 0.55, 1
                halign: 'left'
                text_size: self.size
                bold: True

            BoxLayout:
                size_hint_y: None
                height: '42dp'
                spacing: '8dp'

                Label:
                    id: preview_label
                    text: '07:16 AM'
                    font_size: '34sp'
                    bold: True
                    color: 1, 1, 1, 1
                    halign: 'left'
                    valign: 'middle'
                    text_size: self.size

                Widget:
                    size_hint: None, None
                    size: '10dp', '10dp'
                    pos_hint: {'center_y': 0.5}
                    canvas.before:
                        Color:
                            rgba: 0.95, 0.15, 0.15, 1
                        Ellipse:
                            pos: self.pos
                            size: self.size

        FloatLayout:
            size_hint_y: 1

            Widget:
                size_hint: 1, None
                height: '54dp'
                pos_hint: {'center_x': 0.5, 'center_y': 0.5}
                canvas.before:
                    Color:
                        rgba: 0.9, 0.1, 0.1, 0.15
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [14,]
                    Color:
                        rgba: 0.9, 0.15, 0.15, 1
                    Line:
                        rounded_rectangle: [self.x, self.y, self.width, self.height, 14]
                        width: 1.5

            BoxLayout:
                size_hint: 1, 1
                pos_hint: {'center_x': 0.5, 'center_y': 0.5}
                spacing: '8dp'

                SmoothWheelView:
                    id: rv_hours

                SmoothWheelView:
                    id: rv_minutes

                SmoothWheelView:
                    id: rv_ampm

        BoxLayout:
            size_hint_y: None
            height: '52dp'
            spacing: '14dp'

            Button:
                text: 'MORE OPTIONS'
                background_normal: ''
                background_color: 0, 0, 0, 0
                color: 0.85, 0.85, 0.85, 1
                font_size: '13sp'
                bold: True
                canvas.before:
                    Color:
                        rgba: 0.35, 0.35, 0.35, 1
                    Line:
                        rounded_rectangle: [self.x, self.y, self.width, self.height, 26]
                        width: 1.2

            Button:
                text: 'DONE'
                background_normal: ''
                background_color: 0, 0, 0, 0
                color: 1, 1, 1, 1
                font_size: '13sp'
                bold: True
                canvas.before:
                    Color:
                        rgba: 0.85, 0.12, 0.12, 1
                    RoundedRectangle:
                        pos: self.pos
                        size: self.size
                        radius: [26,]
'''

class WheelItem(Label):
    text = StringProperty('')
    is_selected = BooleanProperty(False)

class SmoothWheelView(RecycleView):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.bind(scroll_y=self.on_scroll_y_changed)

    def on_scroll_y_changed(self, *args):
        if not self.data:
            return
        
        max_y = self.convert_distance_to_scroll(0, self.viewport_size[1] - self.height)[1]
        if max_y <= 0:
            current_progress = 0
        else:
            current_progress = max(0, min(1, self.scroll_y / max_y))
            
        total_items = len(self.data)
        selected_index = round((total_items - 1) * (1 - current_progress))
        selected_index = max(0, min(total_items - 1, selected_index))

        for idx, item in enumerate(self.data):
            new_state = (idx == selected_index)
            if item['is_selected'] != new_state:
                item['is_selected'] = new_state
                self.refresh_from_data()

    def on_touch_up(self, touch):
        handled = super().on_touch_up(touch)
        if touch.grab_current == self or self.collide_point(*touch.pos):
            Clock.schedule_once(self.snap_to_nearest, 0.1)
        return handled

    def snap_to_nearest(self, dt):
        if not self.data:
            return
        
        max_y = self.convert_distance_to_scroll(0, self.viewport_size[1] - self.height)[1]
        if max_y <= 0:
            return
        
        current_progress = max(0, min(1, self.scroll_y / max_y))
        total_items = len(self.data)
        selected_index = round((total_items - 1) * (1 - current_progress))
        selected_index = max(0, min(total_items - 1, selected_index))

        target_progress = 1.0 - (selected_index / (total_items - 1)) if total_items > 1 else 0
        self.scroll_y = target_progress * max_y

class AlarmPickerUI(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ids.rv_hours.data = [{'text': f"{i:02d}", 'is_selected': (i == 7)} for i in range(1, 13)]
        self.ids.rv_minutes.data = [{'text': f"{i:02d}", 'is_selected': (i == 16)} for i in range(60)]
        self.ids.rv_ampm.data = [
            {'text': 'AM', 'is_selected': True},
            {'text': 'PM', 'is_selected': False}
        ]

class TestApp(App):
    def build(self):
        Builder.load_string(KV)
        return AlarmPickerUI()

if __name__ == '__main__':
    TestApp().run()