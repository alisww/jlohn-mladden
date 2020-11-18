import music21
from music21 import stream, note, meter, tempo
from music21.converter.subConverters import ConverterMusicXML
from music21.musicxml import m21ToXml
from musthe import Scale, Note
import math
import io
import requests
from bs4 import BeautifulSoup
import math
import pydub

class Vocaloid:
    def __init__(self,sound_manager):
        self._queue = []
        self._sound = sound_manager

    def say(self,message):
        print("Appending: " + message)
        self._queue.append(self.synthesize(self.compose("B","minor_pentatonic",message)))
        self.sing()

    def sing(self):
        for s in self._queue:
            print("Singing!")
            self._sound.play_sound(s)
        self._queue = []

    def compose(self,key,scale,lyric):
        lyric_split = lyric.replace('\n','').split(" ")

        notes = stream.Stream()
        notes.append(meter.TimeSignature('4/4'))
        notes.append(tempo.MetronomeMark(number=86))

        s = list(Scale(Note(key),scale)) * math.ceil(len(lyric_split) / 4)
        for (i,n) in enumerate(lyric_split):
            n1 = note.Note(str(s[i])+'4')
            n1.quarterLength = 1.0
            n1.lyric = n
            notes.append(n1)

        out = io.BytesIO()
        notes = notes.makeMeasures()

        converter = m21ToXml.GeneralObjectExporter(notes)
        return converter.parse().decode("utf-8")

    def synthesize(self,xml):
        files = {
            'SPKR_LANG': (None, 'english'),
            'SPKR': (None, '4'),
            'SYNALPHA': (None, '0.55'),
            'VIBPOWER': (None, '1'),
            'F0SHIFT': (None, '0'),
            'SYNSRC': ('uwu.xml',xml),
        }

        up_r = requests.post('http://sinsy.sp.nitech.ac.jp/index.php', files=files)
        soup = BeautifulSoup(up_r.text)
        link = "http://sinsy.sp.nitech.ac.jp/" + soup.find("a",string="wav")["href"][2:]

        down_r = requests.get(link)
        rawrxd = io.BytesIO(down_r.content)
        return pydub.AudioSegment.from_wav(rawrxd)
