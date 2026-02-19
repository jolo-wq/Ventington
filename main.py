import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import pytz
import os

current_view = None  # für Reminder
startup_test_sent = False  # 🔥 verhindert doppelte Testumfragen

class EventView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.yes = set()
        self.maybe = set()
        self.no = set()

    def remove_user(self, user_id):
        self.yes.discard(user_id)
        self.maybe.discard(user_id)
        self.no.discard(user_id)

    async def update_message(self, interaction):
        embed = interaction.message.embeds[0]

        yes_list = "\n".join(f"<@{u}>" for u in self.yes) or "-"
        maybe_list = "\n".join(f"<@{u}>" for u in self.maybe) or "-"
        no_list = "\n".join(f"<@{u}>" for u in self.no) or "-"

        embed.set_field_at(0, name=f"👍 Zusagen ({len(self.yes)})", value=yes_list, inline=True)
        embed.set_field_at(1, name=f"🤷 Vielleicht ({len(self.maybe)})", value=maybe_list, inline=True)
        embed.set_field_at(2, name=f"❌ Absagen ({len(self.no)})", value=no_list, inline=True)

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Zusagen", style=discord.ButtonStyle.green, emoji="👍")
    async def yes_button(self, interaction, button):
        self.remove_user(interaction.user.id)
        self.yes.add(interaction.user.id)
        await self.update_message(interaction)

    @discord.ui.button(label="Vielleicht", style=discord.ButtonStyle.gray, emoji="🤷")
    async def maybe_button(self, interaction, button):
        self.remove_user(interaction.user.id)
        self.maybe.add(interaction.user.id)
        await self.update_message(interaction)

    @discord.ui.button(label="Absagen", style=discord.ButtonStyle.red, emoji="❌")
    async def no_button(self, interaction, button):
        self.remove_user(interaction.user.id)
        self.no.add(interaction.user.id)
        await self.update_message(interaction)

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

# ---------- Panel posten ----------
async def post_poll(channel, text, event_dt):
    global last_poll_message, event_time, current_view

    if last_poll_message:
        try:
            await last_poll_message.delete()
        except:
            pass

    embed = discord.Embed(
        title=text,
        description=f"📅 Event um {event_dt.strftime('%A, %H:%M')}",
        color=discord.Color.blue()
    )

    embed.add_field(name="👍 Zusagen (0)", value="-", inline=True)
    embed.add_field(name="🤷 Vielleicht (0)", value="-", inline=True)
    embed.add_field(name="❌ Absagen (0)", value="-", inline=True)

    view = EventView()
    current_view = view

    msg = await channel.send(embed=embed, view=view)

    last_poll_message = msg
    event_time = event_dt

# ---------- Erinnerungen ----------
async def send_reminder(channel, text):
    if not current_view:
        return

    participants = list(current_view.yes | current_view.maybe)

    if participants:
        mentions = " ".join(f"<@{u}>" for u in participants)
        await channel.send(f"{text}\n{mentions}")

# ---------- Scheduler ----------
@tasks.loop(minutes=1)
async def scheduler():
    global event_time

    now = datetime.now(berlin)
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # Mittwoch -> Donnerstag
    if now.weekday() == 2 and now.hour == 0 and now.minute == 1:
        event_dt = now.replace(hour=19, minute=45)
        await post_poll(channel, "🎲 Freier Spieleabend am Donnerstag, 19:45", event_dt)

    # Freitag -> Dienstag
    if now.weekday() == 4 and now.hour == 0 and now.minute == 1:
        game = get_tuesday_game()
        event_dt = (now + timedelta(days=4)).replace(hour=19, minute=45)

        await post_poll(channel, f"🎮 Spielabend am Dienstag, 19:45\nSpiel: {game}", event_dt)

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
    global startup_test_sent

    print(f"Bot online als {bot.user}")

    bot.add_view(EventView())  # 🔥 macht Buttons persistent
    scheduler.start()

    if not startup_test_sent:
        startup_test_sent = True

        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            test_time = datetime.now(berlin) + timedelta(minutes=2)

            await post_poll(
                channel,
                "🧪 TESTUMFRAGE — Funktioniert der Bot?\nEvent in 2 Minuten",
                test_time
            )


bot.run(TOKEN)




