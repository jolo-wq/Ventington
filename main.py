from dotenv import load_dotenv
load_dotenv()
import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta
import pytz
import os
import json
import re
import random
import aiohttp
 
TOKEN = os.getenv("TOKEN")
 
# ================= CHANNEL / GUILD IDs =================
CHANNEL_ID           = 803255642206240818   # ❓terminzusagen
VORSCHLAG_CHANNEL_ID = 836275816065138688   # 💡spielvorschläge
HIGHSCORE_CHANNEL_ID = 1484576122917228564  # 🏆highscores
ARCHIV_CHANNEL_ID    = 1484937530297155715  # 🗄️archiv
QUACK_CHANNEL_ID     = 802676292318527499   # 💬quack-ecke
MITSPIELEN_CHANNEL_ID = 919537942026944522  # 🎮mitspielen
EINTRITT_CHANNEL_ID  = 802618368804782083   # 🤗eintritt
GUILD_ID             = 802618368804782080
STATE_FILE           = "state.json"
 
berlin = pytz.timezone("Europe/Berlin")
 
STEAM_LINK_RE = re.compile(r"https?://store\.steampowered\.com/app/(\d+)")
MEDALS        = ["🥇", "🥈", "🥉"]
 
SCHMAEHUNGEN = [
    "Wieder einer weniger... 😢",
    "Klassisch. 🙄",
    "Feige! 🐔",
    "Schade, die Gruppe wäre besser mit dir gewesen. Oder auch nicht. 🤷",
    "Verständlich. Niemand mag dich trotzdem. 💀",
    "Und wieder stirbt ein Traum. 🕯️",
    "Ohne dich spielen wir einfach besser. 😇",
    "Okay... wir kommen drüber hinweg. Irgendwann. 😭",
    "Du fehlst uns so sehr. Nicht. 🫠",
    "Möge dein Abend genauso langweilig sein wie diese Absage. 😴",
]
 
MEILENSTEINE = [10, 25, 50, 100, 200]
 
 
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
 
event_time            = datetime.fromisoformat(state["event_time"]).astimezone(berlin) if state.get("event_time") else None
last_poll_message_id  = state.get("last_poll_message_id")
reminder_60_sent      = state.get("reminder_60_sent", False)
reminder_15_sent      = state.get("reminder_15_sent", False)
last_trigger_tuesday  = state.get("last_trigger_tuesday")
last_trigger_thursday = state.get("last_trigger_thursday")
reminder_msg_ids      = state.get("reminder_msg_ids", [])
 
if "vorschlaege"    not in state: state["vorschlaege"]    = {}
if "highscores"     not in state: state["highscores"]     = {"dienstag": {}, "donnerstag": {}}
if "streaks"        not in state: state["streaks"]        = {}   # uid → {"current": int, "best": int}
if "hs_message_id"  not in state: state["hs_message_id"]  = None
if "reminder_msg_ids" not in state: state["reminder_msg_ids"] = []
if "archiv"         not in state: state["archiv"]         = []
if "monatsbericht_msg_id" not in state: state["monatsbericht_msg_id"] = None
 
current_view     = None
current_event_day = None   # "dienstag" oder "donnerstag" — für Archiv
 
 
# ================= BOT =================
 
class MyBot(commands.Bot):
    async def setup_hook(self):
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print("Slash-Commands synchronisiert!")
 
intents = discord.Intents.all()
bot = MyBot(command_prefix="!", intents=intents)
 
 
# ================= EVENT PANEL =================
 
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
        embed.set_field_at(2, name=f"👎 Absagen ({len(self.no)})",       value=no_list,    inline=True)
 
        self.persist_votes()
        await interaction.response.edit_message(embed=embed, view=self)
 
    @discord.ui.button(label="Zusagen",    style=discord.ButtonStyle.green, emoji="👍", custom_id="vote_yes")
    async def yes_button(self, interaction, button):
        self.remove_user(interaction.user.id)
        self.yes.add(interaction.user.id)
        await self.update_message(interaction)
 
    @discord.ui.button(label="Vielleicht", style=discord.ButtonStyle.gray,  emoji="🤷", custom_id="vote_maybe")
    async def maybe_button(self, interaction, button):
        self.remove_user(interaction.user.id)
        self.maybe.add(interaction.user.id)
        await self.update_message(interaction)
 
    @discord.ui.button(label="Absagen",    style=discord.ButtonStyle.red,   emoji="👎", custom_id="vote_no")
    async def no_button(self, interaction, button):
        uid = interaction.user.id
        war_ja = uid in self.yes
        self.remove_user(uid)
        self.no.add(uid)
        await self.update_message(interaction)
 
        # Schmähung in quack-ecke (nur wenn vorher zugesagt hatte oder neu absagt)
        quack = bot.get_channel(QUACK_CHANNEL_ID)
        if quack:
            schmaehung = random.choice(SCHMAEHUNGEN)
            await quack.send(
                f"{interaction.user.mention} hat abgesagt. {schmaehung}",
                delete_after=30
            )
 
 
# ================= SPIELVORSCHLAG PANEL =================
 
def make_vorschlag_view(app_id: str) -> discord.ui.View:
    class VorschlagView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self._app_id = app_id
 
        def get_data(self):
            return state["vorschlaege"].get(self._app_id, {})
 
        def remove_user(self, uid):
            d = self.get_data()
            for key in ("hat", "spielen", "nein"):
                lst = d.get(key, [])
                if uid in lst:
                    lst.remove(uid)
            state["vorschlaege"][self._app_id] = d
            save_state()
 
        def add_vote(self, uid, category):
            self.remove_user(uid)
            d = self.get_data()
            d.setdefault(category, []).append(uid)
            state["vorschlaege"][self._app_id] = d
            save_state()
 
        async def refresh_embed(self, interaction):
            d       = self.get_data()
            hat     = d.get("hat",     [])
            spielen = d.get("spielen", [])
            nein    = d.get("nein",    [])
 
            def mentions(lst):
                return "\n".join(f"<@{u}>" for u in lst) or "-"
 
            embed = interaction.message.embeds[0]
            embed.set_field_at(0, name=f"❤️ Will spielen! ({len(spielen)})", value=mentions(spielen), inline=True)
            embed.set_field_at(1, name=f"👍 Hab ich schon ({len(hat)})",     value=mentions(hat),     inline=True)
            embed.set_field_at(2, name=f"👎 Kein Interesse ({len(nein)})",   value=mentions(nein),    inline=True)
 
            await interaction.response.edit_message(embed=embed, view=self)
 
        @discord.ui.button(label="Will spielen!",  style=discord.ButtonStyle.green,   emoji="❤️", custom_id=f"vsg_{app_id}_spielen")
        async def btn_spielen(self, interaction, button):
            self.add_vote(interaction.user.id, "spielen")
            await self.refresh_embed(interaction)
 
        @discord.ui.button(label="Hab ich schon",  style=discord.ButtonStyle.gray,    emoji="👍", custom_id=f"vsg_{app_id}_hat")
        async def btn_hat(self, interaction, button):
            self.add_vote(interaction.user.id, "hat")
            await self.refresh_embed(interaction)
 
        @discord.ui.button(label="Kein Interesse", style=discord.ButtonStyle.red,     emoji="👎", custom_id=f"vsg_{app_id}_nein")
        async def btn_nein(self, interaction, button):
            self.add_vote(interaction.user.id, "nein")
            await self.refresh_embed(interaction)
 
    return VorschlagView()
 
 
# ================= STEAM API =================
 
async def fetch_steam_info(app_id: str):
    url = f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=german"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data     = await resp.json()
                app_data = data.get(app_id, {})
                if not app_data.get("success"):
                    return None, None
                info = app_data["data"]
                return info.get("name", "Unbekanntes Spiel"), info.get("header_image", "")
    except Exception:
        return None, None
 
 
# ================= SPIELVORSCHLAG POSTEN =================
 
async def post_vorschlag(channel, app_id: str, steam_url: str, vorschlagender: discord.Member):
    if app_id in state["vorschlaege"]:
        try:
            existing = await channel.fetch_message(state["vorschlaege"][app_id]["message_id"])
            await channel.send(
                f"⚠️ {vorschlagender.mention} Dieses Spiel wurde bereits vorgeschlagen! → {existing.jump_url}",
                delete_after=60
            )
        except Exception:
            pass
        return
 
    name, image = await fetch_steam_info(app_id)
    if not name:
        name = "Unbekanntes Spiel"
 
    embed = discord.Embed(
        title=f"🎮 Spielvorschlag: {name}",
        url=steam_url,
        description=f"Vorgeschlagen von {vorschlagender.mention}",
        color=discord.Color.og_blurple()
    )
    if image:
        embed.set_image(url=image)
 
    embed.add_field(name="❤️ Will spielen! (0)", value="-", inline=True)
    embed.add_field(name="👍 Hab ich schon (0)",  value="-", inline=True)
    embed.add_field(name="👎 Kein Interesse (0)", value="-", inline=True)
 
    view = make_vorschlag_view(app_id)
    msg  = await channel.send(embed=embed, view=view)
 
    state["vorschlaege"][app_id] = {
        "title": name, "url": steam_url, "image": image or "",
        "message_id": msg.id,
        "hat": [], "spielen": [], "nein": [],
    }
    save_state()
 
 
# ================= ON MESSAGE =================
 
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.channel.id == VORSCHLAG_CHANNEL_ID:
        match = STEAM_LINK_RE.search(message.content)
        if match:
            app_id    = match.group(1)
            steam_url = f"https://store.steampowered.com/app/{app_id}"
            await post_vorschlag(message.channel, app_id, steam_url, message.author)
            try:
                await message.delete()
            except Exception:
                pass
        else:
            try:
                await message.delete()
            except Exception:
                pass
            await message.channel.send(
                f"⚠️ {message.author.mention} Hier sind nur Steam-Links erlaubt! "
                f"Einfach den Link aus dem Steam Store einfügen, z.B.: "
                f"`https://store.steampowered.com/app/945360`",
                delete_after=20
            )
    await bot.process_commands(message)
 
 
# ================= STREAK SYSTEM =================
 
def update_streaks(yes_uids: set, all_known_uids: set):
    """
    Aktualisiert Streaks:
    - Wer zugesagt hat → streak +1
    - Wer nicht zugesagt hat → streak reset auf 0
    Gibt Liste von (uid, neuer_streak) zurück wo Meilensteine erreicht wurden.
    """
    meilensteine_erreicht = []
 
    for uid in all_known_uids:
        key     = str(uid)
        current = state["streaks"].get(key, {"current": 0, "best": 0})
 
        if uid in yes_uids:
            current["current"] += 1
            if current["current"] > current["best"]:
                current["best"] = current["current"]
            # Meilenstein?
            total = sum(state["highscores"]["dienstag"].get(key, 0) +
                        state["highscores"]["donnerstag"].get(key, 0)
                        for _ in [1])  # Trick um Gesamtzahl zu berechnen
            gesamt = (state["highscores"]["dienstag"].get(key, 0) +
                      state["highscores"]["donnerstag"].get(key, 0))
            if gesamt in MEILENSTEINE:
                meilensteine_erreicht.append((uid, gesamt))
        else:
            current["current"] = 0
 
        state["streaks"][key] = current
 
    save_state()
    return meilensteine_erreicht
 
 
# ================= ARCHIV =================
 
async def post_archiv_entry(day: str, event_dt: datetime, yes_uids: set, spiel: str = None):
    """Schreibt einen Eintrag ins Archiv."""
    channel = bot.get_channel(ARCHIV_CHANNEL_ID)
    if not channel:
        return
 
    datum = event_dt.strftime("%d.%m.%Y")
    tag   = "Dienstag" if day == "dienstag" else "Donnerstag"
    emoji = "🎮" if day == "dienstag" else "🎲"
 
    spieler = "\n".join(f"<@{u}>" for u in yes_uids) or "Niemand 😢"
 
    embed = discord.Embed(
        title=f"{emoji} {tag}, {datum}",
        color=discord.Color.green() if day == "dienstag" else discord.Color.orange()
    )
    if spiel:
        embed.add_field(name="🕹️ Gespieltes Spiel", value=spiel, inline=False)
    embed.add_field(name=f"👥 Dabei ({len(yes_uids)})", value=spieler, inline=False)
 
    # In state.archiv speichern
    state["archiv"].append({
        "datum":  datum,
        "tag":    tag,
        "spiel":  spiel or "Freie Wahl",
        "spieler": list(yes_uids),
    })
    save_state()
 
    await channel.send(embed=embed)
 
 
# ================= HIGHSCORE =================
 
def record_yes_votes(day: str, yes_uids: set):
    hs = state["highscores"][day]
    for uid in yes_uids:
        key      = str(uid)
        hs[key]  = hs.get(key, 0) + 1
    state["highscores"][day] = hs
    save_state()
 
 
def build_top3(scores: dict) -> str:
    if not scores:
        return "Noch keine Daten"
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    lines = []
    for i, (uid, count) in enumerate(sorted_scores[:3]):
        streak_info = ""
        s = state["streaks"].get(uid, {})
        if s.get("current", 0) >= 3:
            streak_info = f" 🔥{s['current']}"
        lines.append(f"{MEDALS[i]} <@{uid}> — **{count}**{streak_info}")
    return "\n".join(lines)
 
 
def build_top3_gesamt() -> str:
    combined: dict[str, int] = {}
    for day in ("dienstag", "donnerstag"):
        for uid, count in state["highscores"][day].items():
            combined[uid] = combined.get(uid, 0) + count
    if not combined:
        return "Noch keine Daten"
    sorted_scores = sorted(combined.items(), key=lambda x: x[1], reverse=True)
    lines = []
    for i, (uid, count) in enumerate(sorted_scores[:3]):
        lines.append(f"{MEDALS[i]} <@{uid}> — **{count}** gesamt")
    return "\n".join(lines)
 
 
def build_alle_stats() -> str:
    alle_uids = set(state["highscores"]["dienstag"]) | set(state["highscores"]["donnerstag"])
    if not alle_uids:
        return "Noch keine Daten"
    rows = []
    for uid in alle_uids:
        di    = state["highscores"]["dienstag"].get(uid, 0)
        do    = state["highscores"]["donnerstag"].get(uid, 0)
        s     = state["streaks"].get(uid, {})
        streak = f" 🔥{s['current']}" if s.get("current", 0) >= 3 else ""
        best   = f" (Best: {s['best']})" if s.get("best", 0) >= 3 else ""
        rows.append((uid, di, do, di + do, streak, best))
    rows.sort(key=lambda x: x[3], reverse=True)
    lines = []
    for uid, di, do, total, streak, best in rows:
        lines.append(f"<@{uid}>{streak}  🟦 **{di}**  🟧 **{do}**  ⭐ **{total}**{best}")
    return "\n".join(lines)
 
 
async def update_highscore_post():
    channel = bot.get_channel(HIGHSCORE_CHANNEL_ID)
    if not channel:
        print("⚠️ Highscore-Channel nicht gefunden!")
        return
 
    now = datetime.now(berlin)
    embed = discord.Embed(
        title="🏆 Spieleabend Highscores",
        description=f"Zuletzt aktualisiert: {now.strftime('%d.%m.%Y %H:%M')} Uhr",
        color=discord.Color.gold()
    )
    embed.add_field(name="🟦 Top 3 Dienstag",   value=build_top3(state["highscores"]["dienstag"]),   inline=False)
    embed.add_field(name="🟧 Top 3 Donnerstag", value=build_top3(state["highscores"]["donnerstag"]), inline=False)
    embed.add_field(name="⭐ Top 3 Gesamt",     value=build_top3_gesamt(),                           inline=False)
    embed.add_field(name="📊 Alle Spieler  (🟦Di / 🟧Do / ⭐Gesamt)", value=build_alle_stats(),     inline=False)
    embed.set_footer(text="🔥 = aktuelle Streak (ab 3 Events)")
 
    hs_msg_id = state.get("hs_message_id")
    if hs_msg_id:
        try:
            hs_msg = await channel.fetch_message(hs_msg_id)
            await hs_msg.edit(embed=embed)
            return
        except Exception:
            pass
 
    msg = await channel.send(embed=embed)
    state["hs_message_id"] = msg.id
    save_state()
 
 
# ================= MONATSRÜCKBLICK =================
 
async def post_monatsbericht():
    channel = bot.get_channel(QUACK_CHANNEL_ID)
    if not channel:
        return
 
    now    = datetime.now(berlin)
    monat  = (now - timedelta(days=1)).strftime("%B %Y")  # letzter Monat
    archiv = state.get("archiv", [])
 
    # Nur Einträge des letzten Monats
    letzter_monat = (now - timedelta(days=1)).month
    letztes_jahr  = (now - timedelta(days=1)).year
    eintraege = [
        e for e in archiv
        if datetime.strptime(e["datum"], "%d.%m.%Y").month == letzter_monat
        and datetime.strptime(e["datum"], "%d.%m.%Y").year == letztes_jahr
    ]
 
    if not eintraege:
        return
 
    # Wer war am häufigsten dabei?
    zaehler: dict[str, int] = {}
    for e in eintraege:
        for uid in e.get("spieler", []):
            zaehler[str(uid)] = zaehler.get(str(uid), 0) + 1
 
    top = sorted(zaehler.items(), key=lambda x: x[1], reverse=True)[:3]
    top_str = "\n".join(f"{MEDALS[i]} <@{uid}> — {count}x dabei" for i, (uid, count) in enumerate(top))
 
    embed = discord.Embed(
        title=f"📅 Monatsrückblick: {monat}",
        color=discord.Color.purple(),
        description=f"Es gab **{len(eintraege)} Spieleabende** im vergangenen Monat."
    )
    embed.add_field(name="🏆 Fleißigste Spieler", value=top_str or "Keine Daten", inline=False)
 
    spiele = [e["spiel"] for e in eintraege if e.get("spiel") and e["spiel"] != "Freie Wahl"]
    if spiele:
        from collections import Counter
        haeufig = Counter(spiele).most_common(1)[0]
        embed.add_field(name="🕹️ Meistgespieltes Spiel", value=f"{haeufig[0]} ({haeufig[1]}x)", inline=False)
 
    embed.set_footer(text="Dieser Bericht wird in 24 Stunden gelöscht.")
 
    msg = await channel.send(embed=embed)
    state["monatsbericht_msg_id"] = msg.id
    save_state()
 
    # Nach 24h löschen
    await discord.utils.sleep_until(datetime.now(berlin) + timedelta(hours=24))
    try:
        await msg.delete()
        state["monatsbericht_msg_id"] = None
        save_state()
    except Exception:
        pass
 
 
# ================= EVENT POST =================
 
async def post_poll(channel, text, event_dt, day: str = None, spiel: str = None):
    global last_poll_message_id, event_time, current_view, current_event_day
    global reminder_60_sent, reminder_15_sent, reminder_msg_ids
 
    # Abgelaufenes Event auswerten
    if day and current_view:
        yes_uids = current_view.yes
 
        # Archiv-Eintrag
        if event_time:
            await post_archiv_entry(day, event_time, yes_uids, spiel)
 
        # Highscore + Streaks
        all_known = yes_uids | current_view.maybe | current_view.no
        if yes_uids:
            record_yes_votes(day, yes_uids)
            meilensteine = update_streaks(yes_uids, all_known)
            await update_highscore_post()
 
            # Glückwunschnachrichten für Meilensteine
            for uid, gesamt in meilensteine:
                glück_msg = await channel.send(
                    f"🎉 <@{uid}> hat soeben die **{gesamt}. Zusage** erreicht! Absolute Legende! 🏅",
                    delete_after=300
                )
        else:
            update_streaks(set(), all_known)
 
    # Altes Poll + Reminder löschen
    ids_to_delete = []
    if last_poll_message_id:
        ids_to_delete.append(last_poll_message_id)
    ids_to_delete.extend(reminder_msg_ids)
 
    for mid in ids_to_delete:
        try:
            old_msg = await channel.fetch_message(mid)
            await old_msg.delete()
        except Exception:
            pass
 
    reminder_msg_ids = []
    state["reminder_msg_ids"] = []
 
    embed = discord.Embed(
        title=text,
        description=f"📅 Event: {event_dt.strftime('%A, %d.%m. %H:%M')} Uhr",
        color=discord.Color.blue()
    )
    embed.add_field(name="👍 Zusagen (0)",    value="-", inline=True)
    embed.add_field(name="🤷 Vielleicht (0)", value="-", inline=True)
    embed.add_field(name="👎 Absagen (0)",    value="-", inline=True)
 
    view             = EventView()
    current_view     = view
    current_event_day = day
 
    msg = await channel.send(embed=embed, view=view)
 
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
    global reminder_msg_ids
    if not current_view:
        return
    users = list(current_view.yes | current_view.maybe)
    if users:
        mentions = " ".join(f"<@{u}>" for u in users)
        msg = await channel.send(f"{text}\n{mentions}")
        reminder_msg_ids.append(msg.id)
        state["reminder_msg_ids"] = reminder_msg_ids
        save_state()
 
 
# ================= NÄCHSTE EVENTS =================
 
def next_weekday(weekday, hour=19, minute=45):
    now  = datetime.now(berlin)
    days = (weekday - now.weekday()) % 7
    candidate = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate
 
def next_tuesday_1945():  return next_weekday(1)
def next_thursday_1945(): return next_weekday(3)
 
def get_tuesday_game():
    start = berlin.localize(datetime(2025, 3, 25))
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
 
    # Mittwoch 00:01 → Donnerstag-Poll (Dienstags-Zusagen auswerten)
    if now.weekday() == 2 and now.hour == 0 and 1 <= now.minute <= 5:
        if last_trigger_thursday != today_str:
            spiel = get_tuesday_game()
            await post_poll(
                channel,
                "🎲 Freier Spieleabend am Donnerstag, 19:45",
                next_thursday_1945(),
                day="dienstag",
                spiel=spiel
            )
            last_trigger_thursday = today_str
            state["last_trigger_thursday"] = today_str
            save_state()
 
    # Freitag 00:01 → Dienstag-Poll (Donnerstags-Zusagen auswerten)
    if now.weekday() == 4 and now.hour == 0 and 1 <= now.minute <= 5:
        if last_trigger_tuesday != today_str:
            spiel = get_tuesday_game()
            await post_poll(
                channel,
                f"🎮 Spielabend am Dienstag, 19:45\nSpiel: {spiel}",
                next_tuesday_1945(),
                day="donnerstag",
                spiel="Freie Wahl"
            )
            last_trigger_tuesday = today_str
            state["last_trigger_tuesday"] = today_str
            save_state()
 
    # Erster des Monats 08:00 → Monatsrückblick
    if now.day == 1 and now.hour == 8 and now.minute == 0:
        bot.loop.create_task(post_monatsbericht())
 
    # Reminder
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
    dt    = next_tuesday_1945()
    spiel = get_tuesday_game()
    await post_poll(interaction.channel, f"🎮 Spielabend am Dienstag, 19:45\nSpiel: {spiel}", dt)
    await interaction.followup.send(f"✅ Dienstag-Event erstellt für {dt.strftime('%d.%m. %H:%M')} Uhr", ephemeral=True)
 
 
@bot.tree.command(name="donnerstag", description="Erstellt manuell den Donnerstag-Spielabend-Poll")
async def cmd_donnerstag(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    dt = next_thursday_1945()
    await post_poll(interaction.channel, "🎲 Freier Spieleabend am Donnerstag, 19:45", dt)
    await interaction.followup.send(f"✅ Donnerstag-Event erstellt für {dt.strftime('%d.%m. %H:%M')} Uhr", ephemeral=True)
 
 
@bot.tree.command(name="highscore", description="Highscore manuell aktualisieren")
async def cmd_highscore(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await update_highscore_post()
    await interaction.followup.send("✅ Highscore aktualisiert!", ephemeral=True)
 
 
@bot.tree.command(name="random", description="Wählt zufällig einen Spielvorschlag aus")
async def cmd_random(interaction: discord.Interaction):
    # Nur in quack-ecke und mitspielen erlaubt
    if interaction.channel_id not in (QUACK_CHANNEL_ID, MITSPIELEN_CHANNEL_ID):
        await interaction.response.send_message(
            "❌ Dieser Befehl ist nur in 💬quack-ecke und 🎮mitspielen erlaubt!",
            ephemeral=True
        )
        return
 
    # Kandidaten: Spiele mit mind. 1x ✅ oder 👍
    kandidaten = [
        (aid, d) for aid, d in state["vorschlaege"].items()
        if len(d.get("hat", [])) + len(d.get("spielen", [])) >= 1
    ]
 
    if not kandidaten:
        await interaction.response.send_message(
            "😢 Noch keine Spielvorschläge mit Interesse — geht in 💡spielvorschläge und schlagt was vor!",
            ephemeral=True
        )
        return
 
    await interaction.response.defer()
 
    # Dramatische Auswahl-Animation
    loading_texts = [
        "🎰 Das Rad dreht sich...",
        "🎰 Noch läuft es...",
        "🎰 Fast...",
        "🎲 Und das Ergebnis ist...",
    ]
    msg = await interaction.followup.send(loading_texts[0])
    for text in loading_texts[1:]:
        import asyncio
        await asyncio.sleep(1)
        await msg.edit(content=text)
 
    import asyncio
    await asyncio.sleep(1)
 
    aid, data = random.choice(kandidaten)
    titel  = data.get("title", "Unbekannt")
    url    = data.get("url", "")
    image  = data.get("image", "")
    hat    = len(data.get("hat",     []))
    spielen = len(data.get("spielen", []))
 
    embed = discord.Embed(
        title=f"🎲 Zufallsspiel: {titel}",
        url=url,
        description=f"**{hat + spielen}** Leute würden das spielen!",
        color=discord.Color.gold()
    )
    if image:
        embed.set_image(url=image)
    embed.add_field(name="✅ Haben es schon", value=str(hat),     inline=True)
    embed.add_field(name="👍 Würden spielen", value=str(spielen), inline=True)
 
    await msg.edit(content="", embed=embed)
 
 
@bot.tree.command(name="profile", description="Zeigt deine persönlichen Spieleabend-Stats")
async def cmd_profile(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    di  = state["highscores"]["dienstag"].get(uid, 0)
    do  = state["highscores"]["donnerstag"].get(uid, 0)
    s   = state["streaks"].get(uid, {"current": 0, "best": 0})
 
    # Archiv-Auswertung
    archiv         = state.get("archiv", [])
    total_events   = len(archiv)
    dabei_events   = sum(1 for e in archiv if uid in [str(x) for x in e.get("spieler", [])])
    quote          = round((dabei_events / total_events * 100)) if total_events > 0 else 0
 
    # Erstes Event
    erstes = next(
        (e["datum"] for e in archiv if uid in [str(x) for x in e.get("spieler", [])]),
        None
    )
 
    embed = discord.Embed(
        title=f"👤 Profil: {interaction.user.display_name}",
        color=interaction.user.accent_color or discord.Color.blurple()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="🟦 Dienstag-Zusagen",   value=str(di),               inline=True)
    embed.add_field(name="🟧 Donnerstag-Zusagen", value=str(do),               inline=True)
    embed.add_field(name="⭐ Gesamt",             value=str(di + do),           inline=True)
    embed.add_field(name="🔥 Aktuelle Streak",    value=str(s.get("current", 0)), inline=True)
    embed.add_field(name="🏅 Beste Streak",       value=str(s.get("best", 0)),    inline=True)
    embed.add_field(name="📊 Teilnahmequote",     value=f"{quote}% ({dabei_events}/{total_events})", inline=True)
    if erstes:
        embed.add_field(name="📅 Erstes Event dabei", value=erstes, inline=False)
 
    await interaction.response.send_message(embed=embed, ephemeral=True)
 
 
# ================= KALENDER =================
 
@bot.tree.command(name="kalender", description="Zeigt den Spielplan für die nächsten 4 Wochen")
async def cmd_kalender(interaction: discord.Interaction):
    if interaction.channel_id not in (QUACK_CHANNEL_ID, MITSPIELEN_CHANNEL_ID):
        await interaction.response.send_message(
            "❌ Dieser Befehl ist nur in 💬quack-ecke und 🎮mitspielen erlaubt!",
            ephemeral=True
        )
        return
 
    await interaction.response.defer()
 
    now   = datetime.now(berlin)
    lines = []
 
    # Nächste 4 Wochen durchgehen — jeden Dienstag und Donnerstag erfassen
    check = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events_found = 0
 
    while events_found < 8:  # 4 Dienstage + 4 Donnerstage
        # Dienstag = weekday 1
        if check.weekday() == 1:
            spiel = get_tuesday_game_for_date(check)
            datum = check.strftime("%d.%m.")
            woche = check.strftime("KW %W")
            lines.append(f"🟦 **Di {datum}** ({woche}) — 🎮 {spiel}")
            events_found += 1
        # Donnerstag = weekday 3
        elif check.weekday() == 3:
            datum = check.strftime("%d.%m.")
            woche = check.strftime("KW %W")
            lines.append(f"🟧 **Do {datum}** ({woche}) — 🎲 Freie Spielwahl")
            events_found += 1
 
        check += timedelta(days=1)
 
    embed = discord.Embed(
        title="📅 Spielplan — Nächste 4 Wochen",
        description="\n".join(lines),
        color=discord.Color.teal()
    )
    embed.set_footer(text="🟦 Dienstag  |  🟧 Donnerstag  •  Dieser Post löscht sich in 5 Minuten")
 
    msg = await interaction.followup.send(embed=embed)
    await discord.utils.sleep_until(datetime.now(berlin) + timedelta(minutes=5))
    try:
        await msg.delete()
    except Exception:
        pass
 
 
def get_tuesday_game_for_date(dt: datetime) -> str:
    """Berechnet das Spiel für einen beliebigen zukünftigen Dienstag."""
    start = berlin.localize(datetime(2025, 3, 25))
    if dt.tzinfo is None:
        dt = berlin.localize(dt)
    weeks = max((dt - start).days, 0) // 7
    games = ["🛸 Among Us", "🛸 Among Us", "🦆 Goose Goose Duck", "🦆 Goose Goose Duck"]
    return games[weeks % len(games)]
 
 
# ================= ROLLEN =================
 
ROLLEN_GGD = {
    "🪿 Goose (Crewmate)": """**Goose** — Standardrolle. Tasks machen & Ducks voten.
**Adventurer** — Überlebt Umweltgefahren.
**Astral** — Kann als Geist durch Wände fliegen.
**Avenger** — Kann nach beobachtetem Kill zurücktöten.
**Birdwatcher** — Sieht durch Wände, aber eingeschränkte Sicht.
**Bodyguard** — Schützt Spieler und stirbt ggf. für ihn.
**Canadian** — Wird beim Tod automatisch reported.
**Celebrity** — Alle erfahren sofort, wenn du stirbst.
**Detective** — Kann prüfen, ob jemand getötet hat.
**Engineer** — Sieht Sabotagen + kann Vents nutzen.
**Gravy** — Verdient „Belohnung" durch Tasks.
**Locksmith** — Kann Türen jederzeit öffnen.
**Lover** — Mit Partner verbunden – stirbt gemeinsam.
**Medium** — Sieht Anzahl der Geister.
**Mimic** — Wird von Ducks als Duck gesehen.
**Mortician** — Kann Rolle von Leichen sehen.
**Politician** — Gewinnt Ties / schwer rauszuwählen.
**Sheriff** — Kann töten – falscher Kill = Tod.
**Street Urchin** — Kann Schlösser von innen öffnen.
**Stalker** — Verfolgt Spieler.
**Tracker** — Verfolgt Bewegungen.
**Vigilante** — Ein Kill pro Runde möglich.
**Mechanic** — Kann Vents nutzen.
**Technician** — Sieht Sabotagen (ähnlich Engineer).
**Bounty** — Belohnung wenn früh gekillt.""",
 
    "🦆 Duck (Impostor)": """**Duck** — Standard Impostor.
**Assassin** — Kann im Meeting töten (Role guess).
**Morphling** — Verwandelt sich in andere Spieler.
**Cannibal** — Kann Leichen essen.
**Demolitionist** — Platziert Bomben auf Spielern.
**Hitman** — Hat Ziel für Bonus.
**Invisibility Duck** — Kann unsichtbar werden.
**Professional** — Leichen unsichtbar.
**Saboteur** — Stärkere Sabotagen.
**Spy** — Sieht Rollen durch Voting.
**Silencer** — Kann Spieler stumm schalten.
**Undertaker** — Kann Leichen bewegen.
**Miner** — Erstellt neue Vents.
**Cleaner** — Entfernt Leichen komplett.
**Party Duck** — Verzerrt Stimmen (chaotisch).
**Ninja** — Leiser Kill.
**Swooper** — Unsichtbar für kurze Zeit.
**Godfather** — Leader der Ducks.""",
 
    "🎭 Neutral": """**Dodo** — Gewinnt, wenn rausgevotet.
**Dueling Dodo** — Zwei Dodos – einer muss sterben.
**Falcon** — Letzter Überlebender gewinnt.
**Vulture** — Frisst Leichen zum Sieg.
**Pigeon** — Infiziert alle Spieler.
**Pelican** — Verschluckt Spieler.
**Arsonist** — Markiert + zündet alle.
**Serial Killer** — Tötet unabhängig."""
}
 
ROLLEN_AU = {
    "👨‍🚀 Crewmate": """**Crewmate** — Standard.
**Sheriff** — Kann Impostor töten.
**Engineer** — Kann venten.
**Medic** — Schützt Spieler.
**Detective** — Findet Infos nach Kills.
**Time Master** — Spult Zeit zurück.
**Mayor** — Mehr Stimmen.
**Swapper** — Tauscht Votes.
**Seer** — Sieht Rollen.
**Hacker** — Sieht Infos / Admin erweitern.
**Tracker** — Verfolgt Spieler.
**Snitch** — Sieht Impostor bei fast fertigen Tasks.
**Spy** — Sieht Infos über Impostors.
**Security Guard** — Kann Türen schließen / blocken.
**Medium** — Spricht mit Toten.
**Trapper** — Stellt Fallen.
**Veteran** — Kann sich verteidigen (Kill Angreifer).""",
 
    "🔪 Impostor": """**Impostor** — Standard.
**Morphling** — Verwandlung.
**Camouflager** — Alle sehen gleich aus.
**Janitor** — Entfernt Leichen.
**Miner** — Erstellt Vents.
**Undertaker** — Zieht Leichen.
**Assassin** — Kill im Meeting.
**Vampire** — Delayed Kill.
**Warlock** — Zwingt andere zu killen.
**Cleaner** — Entfernt Beweise.
**Bounty Hunter** — Hat Targets.
**Trickster** — Fake Vents.
**Bomber** — Bomben legen.
**Eraser** — Löscht Rollen.""",
 
    "🎭 Neutral": """**Jester** — Gewinnt durch rausvoten.
**Executioner** — Muss Ziel voten lassen.
**Arsonist** — Markieren + anzünden.
**Jackal** — Eigenes Killer-Team.
**Sidekick** — Helfer vom Jackal.
**Vulture** — Frisst Leichen.
**Lawyer** — Schützt Ziel.
**Pursuer** — Upgrade vom Lawyer.
**Serial Killer** — Solo Killer.
**Lover** — Verbundene Spieler."""
}
 
 
@bot.tree.command(name="rollen", description="Zeigt alle Rollen für Among Us oder Goose Goose Duck")
@discord.app_commands.describe(spiel="Welches Spiel?")
@discord.app_commands.choices(spiel=[
    discord.app_commands.Choice(name="🛸 Among Us",        value="au"),
    discord.app_commands.Choice(name="🦆 Goose Goose Duck", value="ggd"),
])
async def cmd_rollen(interaction: discord.Interaction, spiel: str):
    await interaction.response.defer(ephemeral=True)
 
    if spiel == "ggd":
        titel  = "🦆 Goose Goose Duck — Alle Rollen"
        farbe  = discord.Color.yellow()
        rollen = ROLLEN_GGD
    else:
        titel  = "🛸 Among Us — Alle Rollen"
        farbe  = discord.Color.red()
        rollen = ROLLEN_AU
 
    msgs = []
    first = True
    for kategorie, text in rollen.items():
        embed = discord.Embed(color=farbe)
        if first:
            embed.title = titel
            first = False
        embed.add_field(name=kategorie, value=text, inline=False)
        embed.set_footer(text="Löscht sich in 2 Minuten automatisch.")
        msg = await interaction.channel.send(embed=embed)
        msgs.append(msg)
 
    await interaction.followup.send("✅ Rollen gepostet!", ephemeral=True)
 
    await discord.utils.sleep_until(datetime.now(berlin) + timedelta(minutes=2))
    for msg in msgs:
        try:
            await msg.delete()
        except Exception:
            pass
 
 
# ================= REGELN =================
 
SPIELREGELN = """**1.** Während der Runden muten sich alle, da die meisten nicht im Vollmute sind.
 
**2.** Wer tot ist, ist tot und darf erst wieder reden wenn der Endbildschirm zu sehen ist. Auch Privatnachrichten während des Games mit Spielbezug sind verboten.
 
**3.** Fragen zu Aufgaben oder Rollen bitte möglichst erst nach der Runde stellen.
 
**4.** Wer rausgevotet wird, called bitte nicht seine Rolle.
 
**5.** Wenn man bei GGD Pelikan ist, darf man nicht die Glocke betätigen. Verstoß wird mit sofortigem Rausvoten geahndet. Außerdem wird mindestens AllKiller einen Tag lang sauer auf dich sein. 🔔
 
**6.** Wer 3x hintereinander in der ersten Runde als erstes gekillt wird, darf seinen Mörder outcallen. Versucht drauf zu achten, dass nicht immer dieselben als erstes gekillt werden."""
 
SERVERREGELN = """**1.** Nur Admins können Leute einladen. Bitte nur Leute einladen, die ihr kennt und die in unsere Runde passen.
 
**2.** In unsere Runde passt man wenn: man mindestens volljährig ist (lieber über 20), sich angemessen ausdrücken kann, nicht beleidigt und ein Mikro mit angemessener Soundqualität hat.
 
**3.** Jede Woche erscheint eine Terminabfrage. Bitte möglichst frühzeitig zu- oder absagen. Wer nicht eingetragen ist wenn die Gruppe voll ist, kann an dem Abend nicht mitspielen.
 
**4.** Updates werden immer vorher abgesprochen. Bitte nicht einfach updaten ohne Absprache. Wer mit anderen Gruppen updated, bitte den alten Ordner behalten.
 
**5.** Bitte möglichst pünktlich um **19:45 Uhr** am Spieltag im Sprachkanal sein. Falls ihr nicht reinkommt, kurz in der Quack-Ecke Bescheid geben wenn ihr später kommt.
 
**6.** Wenn jemand streamt, kurz Bescheid sagen wenn alle da sind — oder vorher in der Quack-Ecke. Normalerweise sind alle fein damit.
 
**7.** Wer streamt, schummelt selbstverständlich nicht durch Gucken des eigenen Streams.
 
**8.** Wenn Randoms beim Stream fragen ob sie mitspielen können: Wir spielen nur mit Leuten die wir kennen. Nette Dauergäste können wir aber über eine Einladung reden. 😊"""
 
 
@bot.tree.command(name="regeln", description="Zeigt die Spiel- und Serverregeln")
async def cmd_regeln(interaction: discord.Interaction):
    if interaction.channel_id != QUACK_CHANNEL_ID:
        await interaction.response.send_message(
            "❌ Dieser Befehl ist nur in 💬quack-ecke erlaubt!",
            ephemeral=True
        )
        return
 
    await interaction.response.defer(ephemeral=True)
 
    embed1 = discord.Embed(
        title="🎮 Spielregeln",
        description=SPIELREGELN,
        color=discord.Color.blue()
    )
    embed1.set_footer(text="Löscht sich in 2 Minuten automatisch.")
 
    embed2 = discord.Embed(
        title="🖥️ Serverregeln",
        description=SERVERREGELN,
        color=discord.Color.green()
    )
    embed2.set_footer(text="Löscht sich in 2 Minuten automatisch.")
 
    msg1 = await interaction.channel.send(embed=embed1)
    msg2 = await interaction.channel.send(embed=embed2)
 
    await interaction.followup.send("✅ Regeln gepostet!", ephemeral=True)
 
    await discord.utils.sleep_until(datetime.now(berlin) + timedelta(minutes=2))
    for msg in (msg1, msg2):
        try:
            await msg.delete()
        except Exception:
            pass
 
 
# ================= BEGRÜSSUNG =================
 
@bot.event
async def on_member_join(member: discord.Member):
    channel = bot.get_channel(EINTRITT_CHANNEL_ID)
    if not channel:
        return
 
    embed = discord.Embed(
        title=f"👋 Willkommen auf Among Goose, {member.display_name}!",
        description=(
            f"Hey {member.mention}! Schön dass du da bist! 🎉\n\n"
            f"Schau dich gerne um und lies die Regeln in der 💬quack-ecke mit `/regeln`.\n"
            f"Bei Fragen einfach melden — wir beißen nicht. Meistens. 🦆"
        ),
        color=discord.Color.og_blurple()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"Mitglied #{member.guild.member_count}")
 
    await channel.send(embed=embed)
 
 
# ================= START =================
 
@bot.event
async def on_ready():
    global current_view
    print(f"Bot online als {bot.user}")
 
    votes        = state.get("votes", {})
    current_view = EventView(
        yes=votes.get("yes",   []),
        maybe=votes.get("maybe", []),
        no=votes.get("no",    []),
    )
    bot.add_view(current_view)
 
    for app_id in state.get("vorschlaege", {}):
        bot.add_view(make_vorschlag_view(app_id))
 
    scheduler.start()
    print(f"Scheduler gestartet. {len(state.get('vorschlaege', {}))} Spielvorschlag-Views registriert.")
 
 
bot.run(TOKEN)
