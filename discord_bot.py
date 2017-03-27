import discord
from discord.ext import commands
import random
import json, asyncio
import datetime, re
import logging
import sys
import copy
import traceback

description = 'SuperBot !'

if not discord.opus.is_loaded():
    discord.opus.load_opus('opus')

discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.CRITICAL)
log = logging.getLogger()
log.setLevel(logging.INFO)
handler = logging.FileHandler(filename='superbot.log', encoding='utf-8', mode='w')
log.addHandler(handler)

help_attrs = dict(hidden=True)

prefix = ['?', '!', '\N{HEAVY EXCLAMATION MARK SYMBOL}']
bot = commands.Bot(command_prefix=prefix, description=description)

# basic commands 

@bot.event
@asyncio.coroutine
def on_ready():
    print('Logged in as')
    print(bot.user.name)
    print(bot.user.id)
    print('------')

@bot.command()
@asyncio.coroutine 
def add(left : int, right : int):
    """Adds two numbers together."""
    yield from bot.say(left + right)

@bot.command()
@asyncio.coroutine
def roll(*dice : str):
    """Rolls a dice in NdN format."""
    try:
        rolls, limit = map(int, dice.split('d'))
    except Exception:
        yield from bot.say('Format has to be in NdN!')
        return

    result = ', '.join(str(random.randint(1, limit)) for r in range(rolls))
    yield from bot.say(result)

@bot.command(description='For when you wanna settle the score some other way')
@asyncio.coroutine
def choose(*choices : str):
    """Chooses between multiple choices."""
    yield from bot.say(random.choice(choices))

@bot.command()
@asyncio.coroutine
def repeat(times : int, content='repeating...'):
    """Repeats a message multiple times."""
    for i in range(times):
        yield from bot.say(content)

@bot.command()
@asyncio.coroutine
def joined(member : discord.Member):
    """Says when a member joined."""
    yield from bot.say('{0.name} joined in {0.joined_at}'.format(member))

@bot.group(pass_context=True)
@asyncio.coroutine
def cool(ctx):
    """Says if a user is cool.

    In reality this just checks if a subcommand is being invoked.
    """
    if ctx.invoked_subcommand is None:
        yield from bot.say('No, {0.subcommand_passed} is not cool'.format(ctx))

@cool.command(name='bot')
@asyncio.coroutine
def _bot():
    """Is the bot cool?"""
    yield from bot.say('Yes, the bot is cool.')

# end

# advanced commands

## message edit
@bot.event
@asyncio.coroutine
def on_message(message):
    if message.content.startswith('!editme'):
        msg = yield from bot.send_message(message.author, '10')
        yield from asyncio.sleep(3)
        yield from bot.edit_message(msg, '40')

@bot.event
@asyncio.coroutine
def on_message_edit(before, after):
    fmt = '**{0.author}** edited their message:\n{1.content}'
    yield from bot.send_message(after.channel, fmt.format(after, before))

## message delete
@bot.event
@asyncio.coroutine
def on_message(message):
    if message.content.startswith('!deleteme'):
        msg = yield from bot.send_message(message.channel, 'I will delete myself now...')
        yield from bot.delete_message(msg)

@bot.event
@asyncio.coroutine
def on_message_delete(message):
    fmt = '{0.author.name} has deleted the message:\n{0.content}'
    yield from bot.send_message(message.channel, fmt.format(message))

## reply
@bot.event
@asyncio.coroutine
def on_message(message):
    # we do not want the bot to reply to itself
    if message.author == bot.user:
        return

    if message.content.startswith('!hello'):
        msg = 'Hello {0.author.mention}'.format(message)
        yield from bot.send_message(message.channel, msg)
# end

# logs

@bot.event
@asyncio.coroutine
def on_member_join(member):
    server = member.server
    fmt = 'Welcome {0.mention} to {1.name}!'
    yield from bot.send_message(server, fmt.format(member, server))

# end

# music player

class VoiceEntry:
    def __init__(self, message, player):
        self.requester = message.author
        self.channel = message.channel
        self.player = player

    def __str__(self):
        fmt = '*{0.title}* uploaded by {0.uploader} and requested by {1.display_name}'
        duration = self.player.duration
        if duration:
            fmt = fmt + ' [length: {0[0]}m {0[1]}s]'.format(divmod(duration, 60))
        return fmt.format(self.player, self.requester)

class VoiceState:
    def __init__(self, bot):
        self.current = None
        self.voice = None
        self.bot = bot
        self.play_next_song = asyncio.Event()
        self.songs = asyncio.Queue()
        self.skip_votes = set() # a set of user_ids that voted
        self.audio_player = self.bot.loop.create_task(self.audio_player_task())

    def is_playing(self):
        if self.voice is None or self.current is None:
            return False

        player = self.current.player
        return not player.is_done()

    @property
    def player(self):
        return self.current.player

    def skip(self):
        self.skip_votes.clear()
        if self.is_playing():
            self.player.stop()

    def toggle_next(self):
        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)

    @asyncio.coroutine
    def audio_player_task(self):
        while True:
            self.play_next_song.clear()
            self.current = yield from self.songs.get()
            yield from self.bot.send_message(self.current.channel, 'Now playing ' + str(self.current))
            self.current.player.start()
            yield from self.play_next_song.wait()

class Music:
    """Voice related commands.

    Works in multiple servers at once.
    """
    def __init__(self, bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, server):
        state = self.voice_states.get(server.id)
        if state is None:
            state = VoiceState(self.bot)
            self.voice_states[server.id] = state

        return state

    @asyncio.coroutine
    def create_voice_client(self, channel):
        voice = yield from self.bot.join_voice_channel(channel)
        state = self.get_voice_state(channel.server)
        state.voice = voice

    def __unload(self):
        for state in self.voice_states.values():
            try:
                state.audio_player.cancel()
                if state.voice:
                    self.bot.loop.create_task(state.voice.disconnect())
            except:
                pass

    @commands.command(pass_context=True, no_pm=True)
    @asyncio.coroutine
    def join(self, ctx, *, channel : discord.Channel):
        """Joins a voice channel."""
        try:
            yield from self.create_voice_client(channel)
        except discord.ClientException:
            yield from self.bot.say('Already in a voice channel...')
        except discord.InvalidArgument:
            yield from self.bot.say('This is not a voice channel...')
        else:
            yield from self.bot.say('Ready to play audio in ' + channel.name)

    @commands.command(pass_context=True, no_pm=True)
    @asyncio.coroutine
    def summon(self, ctx):
        """Summons the bot to join your voice channel."""
        summoned_channel = ctx.message.author.voice_channel
        if summoned_channel is None:
            yield from self.bot.say('You are not in a voice channel.')
            return False

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            state.voice = yield from self.bot.join_voice_channel(summoned_channel)
        else:
            yield from state.voice.move_to(summoned_channel)

        return True

    @commands.command(pass_context=True, no_pm=True)
    @asyncio.coroutine
    def play(self, ctx, *, song : str):
        """Plays a song.

        If there is a song currently in the queue, then it is
        queued until the next song is done playing.

        This command automatically searches as well from YouTube.
        The list of supported sites can be found here:
        https://rg3.github.io/youtube-dl/supportedsites.html
        """
        state = self.get_voice_state(ctx.message.server)
        opts = {
            'default_search': 'auto',
            'quiet': True,
        }

        if state.voice is None:
            success = yield from ctx.invoke(self.summon)
            if not success:
                return

        try:
            player = yield from state.voice.create_ytdl_player(song, ytdl_options=opts, after=state.toggle_next)
        except Exception as e:
            fmt = 'An error occurred while processing this request: ```py\n{}: {}\n```'
            yield from self.bot.send_message(ctx.message.channel, fmt.format(type(e).__name__, e))
        else:
            player.volume = 0.6
            entry = VoiceEntry(ctx.message, player)
            yield from self.bot.say('Enqueued ' + str(entry))
            yield from state.songs.put(entry)

    @commands.command(pass_context=True, no_pm=True)
    @asyncio.coroutine
    def volume(self, ctx, value : int):
        """Sets the volume of the currently playing song."""

        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.volume = value / 100
            yield from self.bot.say('Set the volume to {:.0%}'.format(player.volume))

    @commands.command(pass_context=True, no_pm=True)
    @asyncio.coroutine
    def pause(self, ctx):
        """Pauses the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.pause()

    @commands.command(pass_context=True, no_pm=True)
    @asyncio.coroutine
    def resume(self, ctx):
        """Resumes the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player
            player.resume()

    @commands.command(pass_context=True, no_pm=True)
    @asyncio.coroutine
    def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.

        This also clears the queue.
        """
        server = ctx.message.server
        state = self.get_voice_state(server)

        if state.is_playing():
            player = state.player
            player.stop()

        try:
            state.audio_player.cancel()
            del self.voice_states[server.id]
            yield from state.voice.disconnect()
        except:
            pass

    @commands.command(pass_context=True, no_pm=True)
    @asyncio.coroutine
    def skip(self, ctx):
        """Vote to skip a song. The song requester can automatically skip.

        3 skip votes are needed for the song to be skipped.
        """

        state = self.get_voice_state(ctx.message.server)
        if not state.is_playing():
            yield from self.bot.say('Not playing any music right now...')
            return

        voter = ctx.message.author
        if voter == state.current.requester:
            yield from self.bot.say('Requester requested skipping song...')
            state.skip()
        elif voter.id not in state.skip_votes:
            state.skip_votes.add(voter.id)
            total_votes = len(state.skip_votes)
            if total_votes >= 3:
                yield from self.bot.say('Skip vote passed, skipping song...')
                state.skip()
            else:
                yield from self.bot.say('Skip vote added, currently at [{}/3]'.format(total_votes))
        else:
            yield from self.bot.say('You have already voted to skip this song.')

    @commands.command(pass_context=True, no_pm=True)
    @asyncio.coroutine
    def playing(self, ctx):
        """Shows info about the currently played song."""

        state = self.get_voice_state(ctx.message.server)
        if state.current is None:
            yield from self.bot.say('Not playing anything.')
        else:
            skip_count = len(state.skip_votes)
            yield from self.bot.say('Now playing {} [skips: {}/3]'.format(state.current, skip_count))

# end

bot.add_cog(Music(bot))
bot.run(token)
handlers = log.handlers[:]
for hdlr in handlers:
    hdlr.close()
    log.removeHandler(hdlr)
