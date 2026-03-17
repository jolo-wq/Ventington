import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import pytz
import os
import json

TOKEN = os.getenv("TOKEN")

CHANNEL_ID = 803255642206240818
GUILD_ID   = 802618368804782080
STATE_FILE = "state.json"

berlin = pytz.timezone("Europe/Berlin")


# ================= STATE PERSISTENCE =================

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state():
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

state = load_state()

# Zustand aus Datei wiederherstellen
event_time           = datetime.fromisoformat(state["event_time"]).astimezone(berlin) if state.get("event_time") else None
last_poll_message_id = state.get("last_poll_message_id")
reminder_60_sent     = state.get("reminder_60_sent", False)
reminder_15_sent     = state.get("reminder_15_sent", False)
last_trigger_tuesday  = state.get("last_trigger_tuesday")   # ISO-Datum-String
last_trigger_thursday = state.get("last_trigger_thursday")  # ISO-Datum-String

current_view = None  # Wird in on_ready gesetzt


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
    def __init__(self, yes=None, maybe=None, no=None):
        super().__init__(timeout=None)
        self.yes   = set(yes   or [])
        self.maybe = set(maybe or [])
        self.no    = set(no    or [])

    def remove_user(self, uid):
        self.yes.discard(uid)
        self.maybe.discard(uid)
        self.no.discard(uid)

    def persist_votes(self):
        state["votes"] = {
            "yes":   list(self.yes),
            "maybe": list(self.maybe),
            "no":    list(self.no),
        }
        save_state()

    async def update_message(self, interaction):
        embed = interaction.message.embeds[0]

        yes_list   = "\n".join(f"<@{u}>" for u in self.yes)   or "-"
        maybe_list = "\n".join(f"<@{u}>" for u in self.maybe) or "-"
        no_list    = "\n".join(f"<@{u}>" for u in self.no)    or "-"

        embed.set_field_at(0, name=f"👍 Zusagen ({len(self.yes)})",      value=yes_list,   inline=True)
        embed.set_field_at(1, name=f"🤷 Vielleicht ({len(self.maybe)})", value=maybe_list, inline=True)
        embed.set_field_at(2, name=f"❌ Absagen ({len(self.no)})",       value=no_list,    inline=True)

        self.persist_votes()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Zusagen",   style=discord.ButtonStyle.green, emoji="👍", custom_id="vote_yes")
    async def yes_button(self, interaction, button):
        self.remove_user(interaction.user.id)
        self.yes.add(interaction.user.id)
        await self.update_message(interaction)

    @discord.ui.button(label="Vielleicht", style=discord.ButtonStyle.gray, emoji="🤷", custom_id="vote_maybe")
    async def maybe_button(self, interaction, button):
        self.remove_user(interaction.user.id)
        self.maybe.add(interaction.user.id)
        await self.update_message(interaction)

    @discord.ui.button(label="Absagen",  style=discord.ButtonStyle.red,  emoji="❌", custom_id="vote_no")
    async def no_button(self, interaction, button):
        self.remove_user(interaction.user.id)
        self.no.add(interaction.user.id)
        await self.update_message(interaction)


# ================= EVENT POST =================

async def post_poll(channel, text, event_dt):
    global last_poll_message_id, event_time, current_view
    global reminder_60_sent, reminder_15_sent

    # Altes Poll löschen (auch nach Neustart via ID)
    if last_poll_message_id:
        try:
            old_msg = await channel.fetch_message(last_poll_message_id)
            await old_msg.delete()
        except Exception:
            pass

    embed = discord.Embed(
        title=text,
        description=f"📅 Event: {event_dt.strftime('%A, %d.%m. %H:%M')} Uhr",
        color=discord.Color.blue()
    )
    embed.add_field(name="👍 Zusagen (0)",    value="-", inline=True)
    embed.add_field(name="🤷 Vielleicht (0)", value="-", inline=True)
    embed.add_field(name="❌ Absagen (0)",    value="-", inline=True)

    view = EventView()
    current_view = view

    msg = await channel.send(embed=embed, view=view)

    # Alles persistieren
    last_poll_message_id = msg.id
    event_time           = event_dt
    reminder_60_sent     = False
    reminder_15_sent     = False

    state["last_poll_message_id"] = msg.id
    state["event_time"]           = event_dt.isoformat()
    state["reminder_60_sent"]     = False
    state["reminder_15_sent"]     = False
    state["votes"]                = {"yes": [], "maybe": [], "no": []}
    save_state()


# ================= REMINDER =================

async def send_reminder(channel, text):
    if not current_view:
        return
    users = list(current_view.yes | current_view.maybe)
    if users:
        mentions = " ".join(f"<@{u}>" for u in users)
        await channel.send(f"{text}\n{mentions}")


# ================= NÄCHSTE EVENTS =================

def next_weekday(weekday, hour=19, minute=45):
    now  = datetime.now(berlin)
    days = (weekday - now.weekday()) % 7
    candidate = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate

def next_tuesday_1945():
    return next_weekday(1)

def next_thursday_1945():
    return next_weekday(3)

def get_tuesday_game():
    # Rotation: ab 25.03.2025 → Among Us (2x), dann Goose Goose Duck (2x), ...
    start = berlin.localize(datetime(2025, 3, 25))  # erster Dienstag der neuen Among-Us-Phase
    now   = datetime.now(berlin)
    weeks = max((now - start).days, 0) // 7
    games = ["🛸 Among Us", "🛸 Among Us", "🦆 Goose Goose Duck", "🦆 Goose Goose Duck"]
    return games[weeks % len(games)]


# ================= SCHEDULER =================

@tasks.loop(minutes=1)
async def scheduler():
    global reminder_60_sent, reminder_15_sent
    global last_trigger_tuesday, last_trigger_thursday

    now     = datetime.now(berlin)
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    today_str = now.date().isoformat()

    # Mittwoch 00:01–00:05 → Donnerstag-Poll posten
    if now.weekday() == 2 and now.hour == 0 and 1 <= now.minute <= 5:
        if last_trigger_thursday != today_str:
            await post_poll(
                channel,
                "🎲 Freier Spieleabend am Donnerstag, 19:45",
                next_thursday_1945()
            )
            last_trigger_thursday = today_str
            state["last_trigger_thursday"] = today_str
            save_state()

    # Freitag 00:01–00:05 → Dienstag-Poll posten
    if now.weekday() == 4 and now.hour == 0 and 1 <= now.minute <= 5:
        if last_trigger_tuesday != today_str:
            await post_poll(
                channel,
                f"🎮 Spielabend am Dienstag, 19:45\nSpiel: {get_tuesday_game()}",
                next_tuesday_1945()
            )
            last_trigger_tuesday = today_str
            state["last_trigger_tuesday"] = today_str
            save_state()

    # ---- Reminder ----
    if event_time:
        delta = event_time - now

        if not reminder_60_sent and timedelta(minutes=55) <= delta <= timedelta(minutes=65):
            await send_reminder(channel, "🔔 Noch 1 Stunde bis zum Event!")
            reminder_60_sent          = True
            state["reminder_60_sent"] = True
            save_state()

        if not reminder_15_sent and timedelta(minutes=10) <= delta <= timedelta(minutes=20):
            await send_reminder(channel, "⚡ Noch 15 Minuten bis zum Event!")
            reminder_15_sent          = True
            state["reminder_15_sent"] = True
            save_state()


# ================= SLASH COMMANDS =================

@bot.tree.command(name="dienstag", description="Erstellt manuell den Dienstag-Spielabend-Poll")
async def cmd_dienstag(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    dt = next_tuesday_1945()
    await post_poll(
        interaction.channel,
        f"🎮 Spielabend am Dienstag, 19:45\nSpiel: {get_tuesday_game()}",
        dt
    )
    await interaction.followup.send(
        f"✅ Dienstag-Event erstellt für {dt.strftime('%d.%m. %H:%M')} Uhr",
        ephemeral=True
    )


@bot.tree.command(name="donnerstag", description="Erstellt manuell den Donnerstag-Spielabend-Poll")
async def cmd_donnerstag(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    dt = next_thursday_1945()
    await post_poll(
        interaction.channel,
        "🎲 Freier Spieleabend am Donnerstag, 19:45",
        dt
    )
    await interaction.followup.send(
        f"✅ Donnerstag-Event erstellt für {dt.strftime('%d.%m. %H:%M')} Uhr",
        ephemeral=True
    )


# ================= START =================

@bot.event
async def on_ready():
    global current_view
    print(f"Bot online als {bot.user}")

    # Votes aus State laden und View mit echten custom_ids registrieren
    votes        = state.get("votes", {})
    current_view = EventView(
        yes=votes.get("yes",   []),
        maybe=votes.get("maybe", []),
        no=votes.get("no",    []),
    )
    bot.add_view(current_view)
    scheduler.start()
    print("Scheduler gestartet, Views registriert.")


bot.run(TOKEN)
