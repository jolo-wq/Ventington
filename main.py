import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import pytz

import os
TOKEN = os.getenv("TOKEN")
CHANNEL_ID = 803255642206240818

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

berlin = pytz.timezone("Europe/Berlin")

last_poll_message = None
event_time = None

# ---------- Spielrotation Dienstag ----------
def get_tuesday_game():
    week = datetime.now(berlin).isocalendar()[1]
    block = (week // 2) % 2
    return "🛸 Among Us" if block == 0 else "🦆 Goose Goose Duck"

# ---------- Umfrage posten ----------
async def post_poll(channel, text, event_dt):
    global last_poll_message, event_time

    if last_poll_message:
        try:
            await last_poll_message.delete()
        except:
            pass

    msg = await channel.send(text)
    await msg.add_reaction("👍")
    await msg.add_reaction("🤷")
    await msg.add_reaction("👎")

    last_poll_message = msg
    event_time = event_dt

# ---------- Teilnehmerliste ----------
async def update_poll(message):
    yes, maybe = [], []

    for reaction in message.reactions:
        users = [u async for u in reaction.users() if not u.bot]

        if str(reaction.emoji) == "👍":
            yes = users
        elif str(reaction.emoji) == "🤷":
            maybe = users

    text = message.content.split("\n\n")[0] + "\n\n"

    if yes:
        text += f"👍 Ja ({len(yes)})\n"
        text += "\n".join(u.mention for u in yes) + "\n\n"

    if maybe:
        text += f"🤷 Vielleicht ({len(maybe)})\n"
        text += "\n".join(u.mention for u in maybe)

    await message.edit(content=text)

# ---------- Doppelvotes verhindern ----------
@bot.event
async def on_reaction_add(reaction, user):
    if user.bot or reaction.message != last_poll_message:
        return

    for react in reaction.message.reactions:
        if react.emoji != reaction.emoji:
            async for u in react.users():
                if u == user:
                    await react.remove(user)

    await update_poll(reaction.message)

# ---------- Erinnerungen ----------
async def send_reminder(channel, text):
    if not last_poll_message:
        return

    yes, maybe = [], []

    for reaction in last_poll_message.reactions:
        users = [u async for u in reaction.users() if not u.bot]

        if str(reaction.emoji) == "👍":
            yes = users
        elif str(reaction.emoji) == "🤷":
            maybe = users

    participants = yes + maybe

    if participants:
        mentions = " ".join(u.mention for u in participants)
        await channel.send(f"{text}\n{mentions}")

# ---------- Scheduler ----------
@tasks.loop(minutes=1)
async def scheduler():
    global event_time

    now = datetime.now(berlin)
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # Mittwoch 00:01 -> Donnerstag
    if now.weekday() == 2 and now.hour == 0 and now.minute == 1:
        event_dt = now.replace(hour=19, minute=45)
        await post_poll(
            channel,
            "🎲 Freier Spieleabend am Donnerstag, 19:45",
            event_dt
        )

    # Freitag 00:01 -> Dienstag
    if now.weekday() == 4 and now.hour == 0 and now.minute == 1:
        game = get_tuesday_game()
        event_dt = now + timedelta(days=4)
        event_dt = event_dt.replace(hour=19, minute=45)

        await post_poll(
            channel,
            f"🎮 Spielabend am Dienstag, 19:45\nSpiel: {game}",
            event_dt
        )

    # Erinnerungen
    if event_time:
        delta = event_time - now

        if timedelta(minutes=59) < delta <= timedelta(minutes=61):
            await send_reminder(channel, "🔔 Noch 1 Stunde!")

        if timedelta(minutes=14) < delta <= timedelta(minutes=16):
            await send_reminder(channel, "⚡ Noch 15 Minuten!")

# ---------- Start ----------
@bot.event
async def on_ready():
    print(f"Bot online als {bot.user}")
    scheduler.start()

    # 🧪 TEST-UMFRAGE SOFORT
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        test_time = datetime.now(berlin) + timedelta(minutes=2)

        await post_poll(
            channel,
            "🧪 TESTUMFRAGE — Funktioniert der Bot?\nEvent in 2 Minuten",
            test_time
        )

bot.run(TOKEN)


