from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os.path
import random
import time
import sys

import pyaudio
import pydub

class SoundManager(object):

    def __init__(self, config):
        self.sound_effects = {}
        sound_root_folder = config['sound_root_folder']
        for name, c in config['sounds'].items():
            path = os.path.join(sound_root_folder, c['file'])
            try:
                self.sound_effects[name] = pydub.AudioSegment.from_wav(path) + c['volume']
            except Exception:
                pass

        self.sound_pool = ThreadPoolExecutor(max_workers=10)
        self._pyaudio = pyaudio.PyAudio()

        self.sound_cues = config['sound_cues']

    def execute_sound(self, sound, delay=0):
        seg = None
        if isinstance(sound,pydub.AudioSegment):
            seg = sound
        elif isinstance(sound, io.IOBase):
            seg = pydub.AudioSegment.from_wav(sound)
        elif isinstance(sound,str) and sound in self.sound_effects:
            seg = self.sound_effects[sound]
        else:
            return

        if delay:
            time.sleep(delay)
        stream = self._pyaudio.open(
            format=self._pyaudio.get_format_from_width(seg.sample_width),
            channels=seg.channels,
            rate=seg.frame_rate,
            output=True,
        )

        try:
            for chunk in pydub.utils.make_chunks(seg, 500):
                stream.write(chunk._data)
        finally:
            stream.stop_stream()
            stream.close()

    def play_sound(self, sound, delay=0):
    #    print(key, file=sys.stderr)
        self.sound_pool.submit(self.execute_sound, sound, delay=delay)

    def cue_sound(self, message):
        if not message:
            return
        for cue in self.sound_cues:
            if cue['trigger'] in message:
                self.play_sound(
                    random.choice(cue['sounds']),
                    delay=cue.get('delay', 0.0),
                )
