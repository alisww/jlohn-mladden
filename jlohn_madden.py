import time
import random
import threading
import queue
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import ujson
import pyttsx3
import requests
import pydub
import pydub.utils
import pyaudio
import yaml

import asyncio
import pprint
from aiohttp_sse_client import client as sse_client


BLASE_MAP = {
    0: 'first',
    1: 'second',
    2: 'third',
}

class UniqueList(list):
    def append(self, value):
        if value not in self:
            super(UniqueList, self).append(value)


class SoundManager(object):

    def __init__(self, sounds):
        self.audio_cues = {}
        for name, config in sounds.items():
            self.audio_cues[name] = pydub.AudioSegment.from_wav(config['file']) + config['volume']

        self.sound_pool = ThreadPoolExecutor(max_workers=10)
        self._pyaudio = pyaudio.PyAudio()

    def execute_sound(self, key, delay=0):
        if delay:
            time.sleep(delay)
        seg = self.audio_cues[key]
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

    def run_sound(self):
        p = pyaudio.PyAudio()
        stream = None
        try:
            while True:
                try:
                    sample = self.q.get()
                    stream = p.open(
                        format=p.get_format_from_width(sample.sample_width),
                        channels=sample.channels,
                        rate=sample.frame_rate,
                        output=True,
                    )
                    for chunk in pydub.utils.make_chunks(sample, 500):
                        stream.write(chunk._data)
                        thread.sleep(0)
                finally:
                    stream.stop_stream()
                    stream.close()
        finally:
            p.terminate()

    def play_sound(self, key, delay=0):
        print(key)
        self.sound_pool.submit(self.execute_sound, key, delay=delay)


class utils(object):
    @staticmethod
    def pronounce_inning(inning):
        if inning == 1:
            return 'first'
        if inning == 2:
            return 'second'
        if inning == 3:
            return 'third'
        return '{}th'.format(inning)

    @staticmethod
    def plural(v):
        return 's' if v > 1 else ''


class PlayerNames(object):

    def __init__(self):
        self._players = {}

    def get(self, id_):
        if id_ in self._players:
            return self._players[id_]
        try:
            player = requests.get('https://blaseball.com/database/players?ids={}'.format(id_))
        except Exception:
            return None
        name = player.json()[0].get('name')
        if name:
            self._players[id_] = name
        return name


player_names = PlayerNames()


class BlaseballGlame(object):

    def __init__(self):
        self.game_logs = []
        self.id_ = ''
        self.away_team = ''
        self.home_team = ''
        self.at_bat = ''
        self.pitching = ''
        self.inning = 1
        self.top_of_inning = False
        self.batting_change = False
        self.away_score = 0
        self.home_score = 0
        self.strikes = 0
        self.balls = 0
        self.outs = 0
        self.on_blase = ['', '', '']
        self.bases_occupied = 0
        self.team_at_bat = ''

        self.last_update = ''

    @property
    def has_runners(self):
        return self.on_blase != ['', '', '']

    @property
    def runners(self):
        runners = []
        for i, player in enumerate(self.on_blase):
            if player:
                runners.append((player, BLASE_MAP[i]))
        return runners

    def update(self, msg):
        """msg should already be json, filtered to the appropriate team"""
        pbp = msg['lastUpdate']
        # self.game_logs.append(pbp)
        # self.sound_effects(pbp)

        self.id_ = msg['id']
        self.away_team = msg['awayTeamName']
        self.home_team = msg['homeTeamName']
        self.away_score = msg['awayScore']
        self.home_score = msg['homeScore']

        self.inning = msg['inning'] + 1
        self.batting_change = msg['topOfInning'] != self.top_of_inning
        self.top_of_inning = msg['topOfInning']  # true means away team at bat

        self.team_at_bat = msg['awayTeamNickname'] if self.top_of_inning else msg['homeTeamNickname']
        self.pitching_team = msg['homeTeamNickname'] if self.top_of_inning else msg['awayTeamNickname']
        at_bat = msg['awayBatterName'] if self.top_of_inning else msg['homeBatterName']
        pitching = msg['homePitcherName'] if self.top_of_inning else msg['awayPitcherName']
        # sometimes these just clear out, don't overwrite if cached
        self.at_bat = at_bat or self.at_bat
        self.pitching = pitching or self.pitching

        self.strikes = msg['atBatStrikes']
        self.balls = msg['atBatBalls']
        self.outs = msg['halfInningOuts']

        self.on_blase = ['', '', '']
        self.bases_occupied = msg['baserunnerCount']
        if msg['baserunnerCount'] > 0:
            for pid, base in zip(msg['baseRunners'], msg['basesOccupied']):
                player_name = player_names.get(pid)
                self.on_blase[base] = player_name or 'runner'
        print(
            'away: {} {}'.format(self.away_team, self.away_score),
            'home: {} {}'.format(self.home_team, self.home_score),
            'inning: {}'.format(self.inning),
            'at_bat: {}'.format(self.at_bat),
            'pitching: {}'.format(self.pitching),
            's|b|o {}|{}|{}'.format(self.strikes, self.balls, self.outs),
            self.on_blase,
        )
        print(pbp)
        self.last_update = pbp
        return pbp


class Quip(object):

    before_index = defaultdict(list)
    after_index = defaultdict(list)

    def __init__(self,
                 phrases,
                 trigger_before=None,
                 trigger_after=None,
                 args=None,
                 chance=1.0,
                 conditions='True'):
        self.phrases = phrases
        self.trigger_before = trigger_before or []
        self.trigger_after = trigger_after or []
        self.args = args or {}
        self.chance = chance
        self.conditions = conditions

        for trigger in self.trigger_before:
            self.before_index[trigger].append(self)
        for trigger in self.trigger_after:
            self.after_index[trigger].append(self)

    @classmethod
    def load(cls, quips):
        """json list"""
        res = []
        for quip in quips:
            res.append(cls(**quip))
        return res

    @classmethod
    def say_quips(cls, play_by_play, game):
        play_by_play = play_by_play.lower()
        quips = UniqueList()
        for term, quip_list in cls.before_index.items():
            for quip in quip_list:
                if term in play_by_play and random.random() < quip.chance and eval(quip.conditions, {}, {'game': game, 'utils': utils}):
                    quips.append(quip.evaluate(play_by_play, game))

        quips.append(play_by_play)

        for term, quip_list in cls.after_index.items():
            for quip in quip_list:
                if term in play_by_play and random.random() < quip.chance and eval(quip.conditions, {}, {'game': game, 'utils': utils}):
                    quips.append(quip.evaluate(play_by_play, game))

        return quips

    def evaluate(self, play_by_play, game):
        args = {}
        for key, equation in self.args.items():
            args[key] = eval(equation, {}, {'game': game, 'utils': utils})
        return random.choice(self.phrases).format(**args)


class Announcer(object):

    def __init__(self, calling_for='Fridays'):
        self.calling_for = calling_for
        self.calling_game = BlaseballGlame()
        self.voice = pyttsx3.init(debug=True)
        self.voice.connect('started-utterance', self.sound_effect)

        self.last_pbps = []

    def on_message(self):
        def callback(message):
            if not message:
                return
            for game in message:
                if self.calling_for in (game['awayTeamNickname'], game['homeTeamNickname']):
                    pbp = self.calling_game.update(game)
                    if not pbp:
                        break
                    quips = Quip.say_quips(pbp, self.calling_game)
                    for quip in quips:
                        if quip in self.last_pbps:
                            continue
                        self.last_pbps.append(quip)
                        self.voice.say(quip, quip)

                    break
            self.voice.runAndWait()
            self.last_pbps = self.last_pbps[-4:]  # avoid last 4 redundancy
        return callback

    def sound_effect(self, name):
        for cue in sound_cues:
            if cue['trigger'] in name:
                sound_manager.play_sound(
                    random.choice(cue['sounds']),
                    delay=cue['delay'],
                )


async def sse_loop(cb):
    async with sse_client.EventSource('https://www.blaseball.com/events/streamGameData') as src:
        async for event in src:
            payload = ujson.loads(event.data)
            # TODO set up logger
            schedule = payload.get('value', {}).get('schedule')
            delta = time.time() * 1000 - payload['value'].get('lastUpdateTime')
            print(delta)
            if delta < 2000:
                print(schedule)
                cb(schedule)
            else:
                pprint.pprint([s['lastUpdate'] for s in schedule])


def main():
    announcer = Announcer(calling_for='Fridays')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(sse_loop(announcer.on_message()))


def test():
    announcer = Announcer(calling_for='Fridays')

    test_dump = [
        'gameDataUpdate',
        {
            'schedule': [
                {
                    u'id': u'4d26c148-3fe8-4b9a-9f64-7c10a0607423',
                    u'atBatBalls': 0,
                    u'atBatStrikes': 0,
                    u'awayBatter': u'',
                    u'awayBatterName': u'',
                    u'awayOdds': 0.5585154403765049,
                    u'awayPitcher': u'bf122660-df52-4fc4-9e70-ee185423ff93',
                    u'awayPitcherName': u'Walton Sports',
                    u'awayScore': 6,
                    u'awayStrikes': 3,
                    u'awayTeam': u'a37f9158-7f82-46bc-908c-c9e2dda7c33b',
                    u'awayTeamBatterCount': 11,
                    u'awayTeamColor': u'#6388ad',
                    u'awayTeamEmoji': u'0x1F450',
                    u'awayTeamName': u'Hawaii Fridays',
                    u'awayTeamNickname': u'Fridays',
                    u'baseRunners': [u'd8ee256f-e3d0-46cb-8c77-b1f88d8c9df9'],
                    u'baserunnerCount': 1,
                    u'basesOccupied': [0],
                    u'day': 93,
                    u'finalized': False,
                    u'gameComplete': False,
                    u'gameStart': True,
                    u'halfInningOuts': 2,
                    u'halfInningScore': 0,
                    u'homeBatter': u'',
                    u'homeBatterName': u'',
                    u'homeOdds': 0.44148455962349503,
                    u'homePitcher': u'd0d7b8fe-bad8-481f-978e-cb659304ed49',
                    u'homePitcherName': u'Adalberto Tosser',
                    u'homeScore': 0,
                    u'homeStrikes': 3,
                    u'homeTeam': u'8d87c468-699a-47a8-b40d-cfb73a5660ad',
                    u'homeTeamBatterCount': 5,
                    u'homeTeamColor': u'#593037',
                    u'homeTeamEmoji': u'0x1F980',
                    u'homeTeamName': u'Baltimore Crabs',
                    u'homeTeamNickname': u'Crabs',
                    u'inning': 2,
                    u'isPostseason': False,
                    u'lastUpdate': u"someone was incinerated",
                    u'outcomes': [],
                    u'phase': 3,
                    u'rules': u'4ae9d46a-5408-460a-84fb-cbd8d03fff6c',
                    u'season': 2,
                    u'seriesIndex': 1,
                    u'seriesLength': 3,
                    u'shame': False,
                    u'statsheet': u'ec7b5639-ddff-4ffa-8181-87710bbd02cd',
                    u'terminology': u'b67e9bbb-1495-4e1b-b517-f1444b0a6c8b',
                    u'topOfInning': True,
                u'weather': 11}
            ]
        },
    ]

    announcer.on_message()(ujson.dumps(test_dump[1]['schedule']))
    return


with open('./quips.yaml', 'r') as __f:
    __y = yaml.load(__f)
    sound_manager = SoundManager(__y['sounds'])
    sound_cues = __y['sound_cues']
    Quip.load(__y['quips'])


if __name__ == '__main__':
    main()
