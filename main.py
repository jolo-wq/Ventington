import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import pytz
import os

TOKEN = os.getenv("TOKEN")

CHANNEL_ID = 803255642206240818
GUILD_ID = 802618368804782080

berlin = pytz.timezone("Europe/Berlin")

last_poll_message = None
event_time = None
current_view = None
last_post_date = None  # 🔥 verhindert doppelte Posts pro Tag


# ================= BOT =================

class MyBot(commands.Bot):
    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("Slash-Commands synchronisiert!")


intents = discord.Intents.all()
bot = MyBot(command_prefix="!", intents=intents)


# ================= PANEL =================

class EventView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.yes = set()
        self.maybe = set()
        self.no = set()

    def remove_user(self, uid):
        self.yes.discard(uid)
        self.maybe.discard(uid)
        self.no.discard(uid)

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


# ================= EVENT POST =================

async def post_poll(channel, text, event_dt):
    global last_poll_message, event_time, current_view, last_post_date

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
    last_post_date = datetime.now(berlin).date()


# ================= REMINDER =================

async def send_reminder(channel, text):
    if not current_view:
        return

    users = list(current_view.yes | current_view.maybe)
    if users:
        mentions = " ".join(f"<@{u}>" for u in users)
        await channel.send(f"{text}\n{mentions}")


# ================= SPIELROTATION =================

def get_tuesday_game():
    week = datetime.now(berlin).isocalendar()[1]
    block = (week // 2) % 2
    return "🛸 Among Us" if block == 0 else "🦆 Goose Goose Duck"


# ================= ROBUSTER SCHEDULER =================

@tasks.loop(minutes=1)
async def scheduler():
    global event_time, last_post_date

    now = datetime.now(berlin)
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    today = now.date()

    # 🔥 Mittwoch -> Donnerstag Event
    if now.weekday() == 2 and now.hour == 0 and 0 <= now.minute <= 5:
        if last_post_date != today:
            event_dt = now.replace(hour=19, minute=45)
            await post_poll(channel, "🎲 Freier Spieleabend am Donnerstag, 19:45", event_dt)

    # 🔥 Freitag -> Dienstag Event
    if now.weekday() == 4 and now.hour == 0 and 0 <= now.minute <= 5:
        if last_post_date != today:
            game = get_tuesday_game()
            event_dt = (now + timedelta(days=4)).replace(hour=19, minute=45)
            await post_poll(channel, f"🎮 Spielabend am Dienstag, 19:45\nSpiel: {game}", event_dt)

    # 🔔 Erinnerungen
    if event_time:
        delta = event_time - now

        if timedelta(minutes=59) < delta <= timedelta(minutes=61):
            await send_reminder(channel, "🔔 Noch 1 Stunde!")

        if timedelta(minutes=14) < delta <= timedelta(minutes=16):
            await send_reminder(channel, "⚡ Noch 15 Minuten!")


# ================= FORCE COMMANDS =================

@bot.tree.command(name="forceevent", description="Startet Dienstag-Event sofort")
async def forceevent(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    game = get_tuesday_game()
    event_dt = datetime.now(berlin) + timedelta(minutes=2)

    await post_poll(
        interaction.channel,
        f"🎮 FORCED Spielabend (Dienstag)\nSpiel: {game}",
        event_dt
    )

    await interaction.followup.send("✅ Dienstag-Event gestartet!", ephemeral=True)


@bot.tree.command(name="forcethursday", description="Startet Donnerstag-Event sofort")
async def forcethursday(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    event_dt = datetime.now(berlin) + timedelta(minutes=2)

    await post_poll(
        interaction.channel,
        "🎲 FORCED Freier Spieleabend (Donnerstag)",
        event_dt
    )

    await interaction.followup.send("✅ Donnerstag-Event gestartet!", ephemeral=True)


# ================= START =================

@bot.event
async def on_ready():
    print(f"Bot online als {bot.user}")

    bot.add_view(EventView())
    scheduler.start()


bot.run(TOKEN)



