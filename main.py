import os
import re
import difflib
import asyncio
from typing import List, Dict, Any, Optional, Tuple

import discord
from discord.ext import commands
from discord import app_commands

import asyncpg

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant (Railway > Variables).")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL manquant (Railway > Add PostgreSQL puis Variables auto).")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

pool: Optional[asyncpg.Pool] = None

# ----------------------------
# Seed : base compétitive (exemples)
# Tu peux enrichir ensuite via /ruling_add
# ----------------------------
SEED_RULINGS: List[Dict[str, Any]] = [
    # --- Règles/chaînes ---
    {"key": "damage step", "title": "Damage Step", "content": "Damage Step: fenêtre restrictive. En général, seuls certains effets (modifs ATK/DEF, effets qui mentionnent Damage Step, certains contres) peuvent être activés.", "tags": ["rules", "combat", "damage step"], "archetype": None, "format": "general"},
    {"key": "miss timing", "title": "Miss Timing", "content": "Miss timing: concerne souvent les effets 'When... you can'. Si l’événement n’est pas la dernière chose arrivée, l’effet optionnel peut rater le timing.", "tags": ["rules", "timing", "chain"], "archetype": None, "format": "general"},
    {"key": "cost vs effect", "title": "Cost vs Effect", "content": "Les coûts sont payés à l’activation, avant que l’adversaire réponde. Si un coût est payé, il n’est pas “remboursé” même si l’effet est annulé.", "tags": ["rules", "cost"], "archetype": None, "format": "general"},
    {"key": "targeting", "title": "Targeting", "content": "Un effet qui cible choisit sa cible à l’activation. En TCG, si la carte ne dit pas 'target', elle ne cible pas.", "tags": ["rules", "target"], "archetype": None, "format": "general"},
    {"key": "chain resolution", "title": "Chain Resolution", "content": "Les chaînes se résolvent à l’envers (CL2 avant CL1). Un effet déjà activé se résout même si la carte est détruite, sauf si l’effet exige sa présence.", "tags": ["rules", "chain"], "archetype": None, "format": "general"},
    {"key": "negate activation vs effect", "title": "Negate Activation vs Negate Effect", "content": "Annuler l’activation stoppe la carte/effet entièrement. Annuler l’effet laisse l’activation exister mais empêche l’effet de s’appliquer.", "tags": ["rules", "negate"], "archetype": None, "format": "general"},
    {"key": "once per turn", "title": "Once per turn", "content": "Un 'once per turn' (sans le nom) peut souvent être réutilisé si la carte quitte le terrain et revient. Un 'you can only use the effect of X once per turn' est un hard OPT.", "tags": ["rules", "opt"], "archetype": None, "format": "general"},
    {"key": "last known information", "title": "Last Known Information", "content": "Si une carte quitte le terrain avant la résolution, le jeu peut utiliser sa dernière information connue pour résoudre certains effets (selon le texte).", "tags": ["rules", "lki"], "archetype": None, "format": "general"},
    {"key": "banish facedown", "title": "Banish face-down", "content": "Bannie face verso = info cachée: beaucoup d’effets ne peuvent pas l’identifier/choisir comme carte précise.", "tags": ["rules", "banish"], "archetype": None, "format": "general"},
    {"key": "special summon legality", "title": "Proper Summon requirement", "content": "Beaucoup de monstres Extra Deck doivent être d’abord invoqués correctement avant de pouvoir être réinvoqués depuis GY/banni.", "tags": ["rules", "extra deck"], "archetype": None, "format": "general"},

    # --- Staples/hand traps ---
    {"key": "ash blossom", "title": "Ash Blossom & Joyous Spring", "content": "Peut répondre à un effet qui: (1) ajoute du Deck à la main, (2) envoie du Deck au GY, (3) SS depuis le Deck.", "tags": ["hand trap", "staple", "negate"], "archetype": None, "format": "tcg"},
    {"key": "effect veiler", "title": "Effect Veiler", "content": "Annule les effets d’un monstre face recto sur le terrain jusqu’à la fin du tour (ne détruit pas).", "tags": ["hand trap", "staple", "negate"], "archetype": None, "format": "tcg"},
    {"key": "infinite impermanence", "title": "Infinite Impermanence", "content": "Annule un monstre ciblé. Activable depuis la main si tu ne contrôles aucune carte.", "tags": ["staple", "trap", "negate"], "archetype": None, "format": "tcg"},
    {"key": "nibiru", "title": "Nibiru, the Primal Being", "content": "Activable après la 5e invocation du tour. Sacrifie tous les monstres sur le terrain, puis donne un Jeton au joueur adverse.", "tags": ["hand trap", "staple"], "archetype": None, "format": "tcg"},
    {"key": "ghost ogre", "title": "Ghost Ogre & Snow Rabbit", "content": "Détruit la carte dont l’effet est activé sur le terrain, mais n’annule pas l’effet (sauf cas dépendant de présence).", "tags": ["hand trap", "staple"], "archetype": None, "format": "tcg"},
    {"key": "droll", "title": "Droll & Lock Bird", "content": "Après qu’une carte a été ajoutée de Deck à la main, empêche d’autres ajouts de Deck à la main ce tour.", "tags": ["hand trap", "staple"], "archetype": None, "format": "tcg"},
    {"key": "dimension shifter", "title": "Dimension Shifter", "content": "Si aucun carte dans ton GY: tout ce qui serait envoyé au GY est banni à la place jusqu’à la fin du tour adverse.", "tags": ["hand trap", "staple", "banish"], "archetype": None, "format": "tcg"},
    {"key": "called by the grave", "title": "Called by the Grave", "content": "Bannit un monstre dans un GY et annule ses effets, et ceux des monstres du même nom, jusqu’à la fin du prochain tour.", "tags": ["staple", "counter"], "archetype": None, "format": "tcg"},
    {"key": "crossout designator", "title": "Crossout Designator", "content": "Déclare une carte; bannit une copie de ton deck puis annule les effets des cartes du même nom ce tour.", "tags": ["staple", "counter"], "archetype": None, "format": "tcg"},
    {"key": "forbidden droplet", "title": "Forbidden Droplet", "content": "Envoie des cartes au GY (souvent coût) pour réduire ATK et annuler effets; les cartes envoyées déterminent ce à quoi l’adversaire peut répondre.", "tags": ["staple", "negate"], "archetype": None, "format": "tcg"},
    {"key": "dark ruler no more", "title": "Dark Ruler No More", "content": "Annule les monstres face recto de l’adversaire ce tour; l’adversaire ne peut pas répondre avec des effets de monstres.", "tags": ["staple", "board breaker"], "archetype": None, "format": "tcg"},

    # --- Archetypes (exemples) ---
    {"key": "branded fusion", "title": "Branded Fusion (général)", "content": "Branded Fusion envoie du Deck au GY comme partie de la résolution (souvent stoppable par Ash). Attention aux restrictions de l’effet ce tour.", "tags": ["branded", "fusion"], "archetype": "branded", "format": "tcg"},
    {"key": "tear chain building", "title": "Tearlaments (triggers GY)", "content": "Beaucoup d’effets Tear se déclenchent quand envoyés au GY. Ordre de chaîne peut dépendre des triggers simultanés et du joueur actif.", "tags": ["tear", "graveyard", "chain"], "archetype": "tearlaments", "format": "tcg"},
    {"key": "labrynth traps", "title": "Labrynth (traps)", "content": "Labrynth tourne autour des pièges Normaux. Attention aux timings: activation de pièges, résolution et triggers associés.", "tags": ["labrynth", "trap"], "archetype": "labrynth", "format": "tcg"},
]

# Pour atteindre ~100 seeds sans te spammer 2000 lignes,
# on génère des entrées supplémentaires “compétitives” cohérentes.
# Tu pourras les remplacer par du plus détaillé ensuite.
EXTRA_SEED_TOPICS = [
    ("battle phase windows", "Battle Phase windows", "Début BP, Step d’attaque, Damage Step, fin BP: certaines activations ne sont possibles que dans certaines fenêtres.", ["rules", "combat"]),
    ("damage calculation", "Damage Calculation", "Damage Calculation: sous-fenêtre de la Damage Step où les activations sont encore plus limitées.", ["rules", "combat"]),
    ("quick effects timing", "Quick Effects timing", "Les Quick Effects peuvent être utilisés en réponse dans une chaîne si la Spell Speed le permet et si la fenêtre d’activation est légale.", ["rules", "timing"]),
    ("trigger vs quick", "Trigger vs Quick", "Un Trigger s’active après un événement; un Quick Effect s’active à vitesse rapide (Spell Speed 2 en général).", ["rules"]),
    ("flip timing", "Flip effects timing", "Les Flip Effects se déclenchent quand le monstre est retourné face recto, y compris par attaque ou effet.", ["rules"]),
    ("set turn rule", "Set turn rule", "La plupart des pièges ne peuvent pas être activés le tour où ils sont posés (sauf exceptions).", ["rules"]),
    ("continuous vs activated", "Continuous vs Activated", "Effets continus s’appliquent tant que la carte reste active; effets activés créent une chaîne.", ["rules"]),
    ("send vs destroy", "Send vs Destroy", "Envoyer au GY n’est pas détruire: protections 'cannot be destroyed' ne s’appliquent pas à 'send'.", ["rules"]),
    ("banish vs send", "Banish vs Send", "Bannir n’est pas envoyer au GY: les triggers 'if sent to GY' ne se déclenchent pas si banni.", ["rules", "banish"]),
    ("public knowledge", "Public knowledge", "Les cartes face recto sont information publique; face verso ne le sont pas.", ["rules"]),
    ("soft once per turn", "Soft once per turn", "Soft OPT: souvent réutilisable si la carte quitte/revient. Hard OPT: limité par le nom.", ["rules", "opt"]),
    ("negate summon", "Negate a Summon", "Annuler une invocation se fait à la fenêtre d’invocation, avant que le monstre ne soit considéré comme 'sur le terrain'.", ["rules", "negate"]),
    ("cannot be targeted", "Cannot be targeted", "Une carte non-ciblable ne peut pas être choisie comme cible; les effets non-ciblants peuvent encore l’affecter.", ["rules", "protection"]),
    ("cannot be destroyed", "Cannot be destroyed", "Protection contre destruction ne protège pas contre 'send', 'banish', 'tribute', 'return to hand/deck'.", ["rules", "protection"]),
    ("banish facedown interactions", "Face-down banish interactions", "Les cartes bannies face verso sont difficiles à référencer: beaucoup d’effets demandent une carte identifiable.", ["rules", "banish"]),
    ("replay", "Replay", "Replay: si le nombre de monstres de la cible change pendant la Battle Step, un replay peut se produire.", ["rules", "combat"]),
    ("mandatory triggers order", "Mandatory triggers order", "Les triggers obligatoires doivent être placés dans la chaîne quand ils s’appliquent; l’ordre peut dépendre des règles de chaînage.", ["rules", "chain"]),
    ("simultaneous triggers", "Simultaneous triggers", "Quand plusieurs triggers se produisent en même temps, on construit la chaîne selon les règles (joueur actif/ina ctif, etc.).", ["rules", "chain"]),
    ("spell speed 1 2 3", "Spell Speed 1/2/3", "SS1 ne répond pas à une chaîne; SS2 peut répondre à SS1/2; SS3 (Counter Trap) répond à tout sauf SS0.", ["rules", "chain"]),
]

def expand_seed_to_100() -> List[Dict[str, Any]]:
    out = list(SEED_RULINGS)
    i = 1
    # Génère des sujets "staples" et "board breakers" supplémentaires
    more_cards = [
        ("lightning storm", "Lightning Storm", "Détruit S/T ou monstres attaquants selon l’option; dépend des conditions d’activation.", ["staple", "board breaker"], None, "tcg"),
        ("raigeki", "Raigeki", "Détruit les monstres adverses; n’annule pas les effets déjà activés.", ["staple", "board breaker"], None, "tcg"),
        ("harpie feather duster", "Harpie's Feather Duster", "Détruit toutes les S/T adverses; attention aux protections/effets de remplacement.", ["staple", "board breaker"], None, "tcg"),
        ("evenly matched", "Evenly Matched", "À la fin BP: l’adversaire bannit face verso jusqu’à ce que vous ayez le même nombre de cartes; très fort en going second.", ["staple", "board breaker", "banish"], None, "tcg"),
        ("cosmic cyclone", "Cosmic Cyclone", "Bannit une S/T (n’est pas une destruction).", ["staple", "banish"], None, "tcg"),
        ("twin twisters", "Twin Twisters", "Défausse 1 (souvent coût) pour détruire 2 S/T.", ["staple"], None, "tcg"),
        ("book of moon", "Book of Moon", "Retourne un monstre face verso; peut couper des liens, des effets, ou éviter des ciblages.", ["staple", "utility"], None, "tcg"),
        ("book of eclipse", "Book of Eclipse", "Flip face verso puis pioche en End Phase si toujours face verso; peut forcer des fenêtres de flip.", ["staple", "utility"], None, "tcg"),
        ("kaijus", "Kaijus (général)", "Tribute (sacrifie) un monstre adverse: contourne beaucoup de protections.", ["staple", "board breaker"], None, "tcg"),
        ("sphere mode", "Sphere Mode", "Tribute 3 monstres adverses: ne détruit pas, contourne les protections.", ["staple", "board breaker"], None, "tcg"),
    ]
    for k, t, c, tags, a, f in more_cards:
        out.append({"key": k, "title": t, "content": c, "tags": tags, "archetype": a, "format": f})

    for k, t, c, tags in EXTRA_SEED_TOPICS:
        out.append({"key": k, "title": t, "content": c, "tags": tags, "archetype": None, "format": "general"})

    # Remplissage jusqu'à 100 avec des entrées “format/archetype” génériques
    archetypes = ["branded", "tearlaments", "labrynth", "kashtira", "snake-eye", "runick", "spright", "swordsoul", "floowandereeze"]
    generic_templates = [
        ("combo starter", "Starter", "Entrée de base: explique le rôle d’un starter et comment l’interrompre (Ash/Veiler/Imperm selon la ligne).", ["competitive", "combo"]),
        ("choke point", "Choke point", "Choke point: l’endroit où une interruption a le plus d’impact (varie selon la main/ligne).", ["competitive", "interaction"]),
        ("resource loop", "Resource loop", "Boucle de ressources: récupération depuis GY/banish; attention aux locks et aux fenêtres de réponse.", ["competitive", "grind"]),
        ("endboard", "Endboard", "Endboard: ce que le deck vise à établir; repère les types de négations/interruptions.", ["competitive", "board"]),
        ("side tips", "Side tips", "Conseils side: quels types de cartes sont efficaces contre ce plan (banish, backrow hate, board breakers).", ["competitive", "side"]),
    ]

    while len(out) < 100:
        arch = archetypes[(i - 1) % len(archetypes)]
        name, title, content, tags = generic_templates[(i - 1) % len(generic_templates)]
        out.append({
            "key": f"{arch} {name} {i}",
            "title": f"{arch.title()} — {title}",
            "content": f"{arch.title()}: {content}",
            "tags": tags + [arch],
            "archetype": arch,
            "format": "tcg"
        })
        i += 1

    return out[:100]

SEED_100 = expand_seed_to_100()

# ----------------------------
# Utilitaires
# ----------------------------
def norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

def tags_to_str(tags: List[str]) -> str:
    return ",".join(sorted({t.strip().lower() for t in tags if t.strip()}))

def str_to_tags(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [t.strip().lower() for t in s.split(",") if t.strip()]

def is_admin(inter: discord.Interaction) -> bool:
    return bool(inter.user and inter.user.guild_permissions.administrator)

# ----------------------------
# DB : init + seed
# ----------------------------
async def db_init():
    async with pool.acquire() as con:
        await con.execute("""
        CREATE TABLE IF NOT EXISTS rulings (
            key TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            archetype TEXT,
            format TEXT
        );
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            count BIGINT NOT NULL DEFAULT 0
        );
        """)
        await con.execute("""
        CREATE TABLE IF NOT EXISTS suggestions (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            author_id TEXT,
            author_name TEXT,
            key TEXT,
            title TEXT,
            content TEXT,
            tags TEXT,
            archetype TEXT,
            format TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
        );
        """)

async def db_seed_if_empty():
    async with pool.acquire() as con:
        n = await con.fetchval("SELECT COUNT(*) FROM rulings;")
        if n and n > 0:
            return
        # Insert seed
        for r in SEED_100:
            await con.execute(
                """INSERT INTO rulings(key, title, content, tags, archetype, format)
                   VALUES($1,$2,$3,$4,$5,$6)
                   ON CONFLICT (key) DO NOTHING;""",
                norm_key(r["key"]),
                r["title"],
                r["content"],
                tags_to_str(r.get("tags", [])),
                r.get("archetype"),
                r.get("format", "general"),
            )

# ----------------------------
# Recherche DB
# ----------------------------
async def db_find_ruling(query: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    """
    Retourne (best, others, suggestions_keys).
    best: meilleur résultat
    others: autres résultats proches (max 5)
    suggestions: difflib sur keys existantes (max 5)
    """
    q = norm_key(query)
    if not q:
        return None, [], []

    async with pool.acquire() as con:
        # exact
        exact = await con.fetchrow("SELECT * FROM rulings WHERE key = $1;", q)

        # partial / title / tag / archetype
        like = f"%{q}%"
        rows = await con.fetch(
            """SELECT * FROM rulings
               WHERE key ILIKE $1
                  OR title ILIKE $1
                  OR tags ILIKE $1
                  OR archetype ILIKE $2
               LIMIT 20;""",
            like,
            q
        )

        # construire liste unique
        seen = set()
        ordered: List[asyncpg.Record] = []
        if exact:
            ordered.append(exact)
            seen.add(exact["key"])
        for r in rows:
            if r["key"] not in seen:
                ordered.append(r)
                seen.add(r["key"])

        # Suggestions (keys)
        keys = await con.fetch("SELECT key FROM rulings LIMIT 5000;")
        key_list = [k["key"] for k in keys]
        suggestions = difflib.get_close_matches(q, key_list, n=5, cutoff=0.55)

        if not ordered:
            return None, [], suggestions

        best = ordered[0]
        others = ordered[1:6]

        def rec_to_dict(rec: asyncpg.Record) -> Dict[str, Any]:
            return {
                "key": rec["key"],
                "title": rec["title"],
                "content": rec["content"],
                "tags": str_to_tags(rec["tags"]),
                "archetype": rec["archetype"],
                "format": rec["format"]
            }

        best_d = rec_to_dict(best)
        others_d = [rec_to_dict(o) for o in others]
        return best_d, others_d, suggestions

async def db_search_rulings(query: str, limit: int = 10) -> Tuple[List[Dict[str, Any]], List[str]]:
    q = norm_key(query)
    if not q:
        return [], []

    async with pool.acquire() as con:
        like = f"%{q}%"
        rows = await con.fetch(
            """SELECT * FROM rulings
               WHERE key ILIKE $1
                  OR title ILIKE $1
                  OR tags ILIKE $1
                  OR archetype ILIKE $2
               ORDER BY key ASC
               LIMIT $3;""",
            like,
            q,
            limit
        )
        keys = await con.fetch("SELECT key FROM rulings LIMIT 5000;")
        key_list = [k["key"] for k in keys]
        suggestions = difflib.get_close_matches(q, key_list, n=5, cutoff=0.55)

    out = []
    for r in rows:
        out.append({
            "key": r["key"],
            "title": r["title"],
            "content": r["content"],
            "tags": str_to_tags(r["tags"]),
            "archetype": r["archetype"],
            "format": r["format"]
        })
    return out, suggestions

async def db_inc_stat(key: str):
    k = norm_key(key)
    async with pool.acquire() as con:
        await con.execute(
            """INSERT INTO stats(key, count) VALUES($1, 1)
               ON CONFLICT (key) DO UPDATE SET count = stats.count + 1;""",
            k
        )

async def db_top_stats(limit: int = 10) -> List[Tuple[str, int]]:
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT key, count FROM stats ORDER BY count DESC LIMIT $1;",
            limit
        )
    return [(r["key"], int(r["count"])) for r in rows]

# ----------------------------
# Embeds
# ----------------------------
def embed_ruling(r: Dict[str, Any]) -> discord.Embed:
    desc = r["content"]
    e = discord.Embed(title=r["title"], description=desc[:4000])
    meta = []
    if r.get("archetype"):
        meta.append(f"Archetype: `{r['archetype']}`")
    if r.get("format"):
        meta.append(f"Format: `{r['format']}`")
    if meta:
        e.add_field(name="Info", value=" • ".join(meta), inline=False)
    tags = r.get("tags", [])
    if tags:
        e.add_field(name="Tags", value=", ".join(tags[:25]), inline=False)
    e.set_footer(text=f"Key: {r['key']}")
    return e

# ----------------------------
# Discord lifecycle
# ----------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id={bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Slash commands sync: {len(synced)}")
    except Exception as e:
        print("⚠️ Sync error:", e)

async def startup():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    await db_init()
    await db_seed_if_empty()

# ----------------------------
# Commands (public)
# ----------------------------
@bot.tree.command(name="ruling", description="Affiche le meilleur ruling (base + archetypes + tags).")
@app_commands.describe(topic="Ex: damage step, ash blossom, branded, labrynth, etc.")
async def ruling(interaction: discord.Interaction, topic: str):
    best, others, suggestions = await db_find_ruling(topic)

    if not best:
        msg = "Je n’ai rien trouvé dans la base."
        if suggestions:
            msg += "\nSuggestions: " + ", ".join(f"`{s}`" for s in suggestions)
        await interaction.response.send_message(msg, ephemeral=True)
        return

    await db_inc_stat(best["key"])

    e = embed_ruling(best)
    if others:
        lines = "\n".join(f"• `{o['key']}` — {o['title']}" for o in others[:5])
        e.add_field(name="Autres résultats proches", value=lines[:1024], inline=False)
    if suggestions:
        e.add_field(name="Suggestions", value=", ".join(f"`{s}`" for s in suggestions), inline=False)

    await interaction.response.send_message(embed=e)

@bot.tree.command(name="ruling_search", description="Liste des résultats (sans afficher tout le contenu).")
@app_commands.describe(query="Mot-clé (key/titre/tags/archetype)")
async def ruling_search(interaction: discord.Interaction, query: str):
    rows, suggestions = await db_search_rulings(query, limit=12)
    if not rows:
        msg = "Aucun résultat."
        if suggestions:
            msg += "\nSuggestions: " + ", ".join(f"`{s}`" for s in suggestions)
        await interaction.response.send_message(msg, ephemeral=True)
        return

    lines = []
    for r in rows:
        extra = []
        if r.get("archetype"):
            extra.append(r["archetype"])
        if r.get("format"):
            extra.append(r["format"])
        extra_txt = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"• `{r['key']}` — {r['title']}{extra_txt}")

    e = discord.Embed(title=f"Résultats pour: {query}", description="\n".join(lines)[:4000])
    if suggestions:
        e.add_field(name="Suggestions", value=", ".join(f"`{s}`" for s in suggestions), inline=False)
    await interaction.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="ruling_stats", description="Top des rulings les plus consultés.")
async def ruling_stats(interaction: discord.Interaction):
    top = await db_top_stats(limit=10)
    if not top:
        await interaction.response.send_message("Aucune statistique pour l’instant.", ephemeral=True)
        return
    text = "\n".join(f"{i+1}. `{k}` — **{c}**" for i, (k, c) in enumerate(top))
    e = discord.Embed(title="📊 Top Rulings", description=text)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="ruling_suggest", description="Propose un ruling (envoyé en attente de validation).")
@app_commands.describe(
    key="Key (ex: evenly matched)",
    title="Titre affiché",
    content="Texte du ruling (résumé, pas copier-coller officiel)",
    tags="Tags séparés par des virgules",
    archetype="Optionnel (ex: branded, tearlaments, labrynth)",
    format="general/tcg/ocg/masterduel"
)
async def ruling_suggest(
    interaction: discord.Interaction,
    key: str,
    title: str,
    content: str,
    tags: Optional[str] = "",
    archetype: Optional[str] = "",
    format: Optional[str] = "general"
):
    async with pool.acquire() as con:
        await con.execute(
            """INSERT INTO suggestions(author_id, author_name, key, title, content, tags, archetype, format, status)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8,'pending');""",
            str(interaction.user.id),
            str(interaction.user),
            norm_key(key),
            title.strip(),
            content.strip(),
            (tags or "").strip(),
            (archetype or "").strip().lower() or None,
            (format or "general").strip().lower()
        )

    await interaction.response.send_message("✅ Suggestion enregistrée. Un admin pourra la valider.", ephemeral=True)

# ----------------------------
# Commands (admin)
# ----------------------------
@bot.tree.command(name="ruling_add", description="(Admin) Ajoute un ruling en base.")
async def ruling_add(
    interaction: discord.Interaction,
    key: str,
    title: str,
    content: str,
    tags: Optional[str] = "",
    archetype: Optional[str] = "",
    format: Optional[str] = "general"
):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return

    async with pool.acquire() as con:
        await con.execute(
            """INSERT INTO rulings(key, title, content, tags, archetype, format)
               VALUES($1,$2,$3,$4,$5,$6)
               ON CONFLICT (key) DO UPDATE
                 SET title=EXCLUDED.title, content=EXCLUDED.content, tags=EXCLUDED.tags,
                     archetype=EXCLUDED.archetype, format=EXCLUDED.format;""",
            norm_key(key),
            title.strip(),
            content.strip(),
            (tags or "").strip(),
            (archetype or "").strip().lower() or None,
            (format or "general").strip().lower(),
        )
    await interaction.response.send_message(f"✅ Ajout/MàJ: `{norm_key(key)}`", ephemeral=True)

@bot.tree.command(name="ruling_edit", description="(Admin) Modifie un ruling existant (par key).")
async def ruling_edit(
    interaction: discord.Interaction,
    key: str,
    title: Optional[str] = "",
    content: Optional[str] = "",
    tags: Optional[str] = "",
    archetype: Optional[str] = "",
    format: Optional[str] = ""
):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return

    k = norm_key(key)
    async with pool.acquire() as con:
        row = await con.fetchrow("SELECT * FROM rulings WHERE key=$1;", k)
        if not row:
            await interaction.response.send_message(f"❌ Key inconnue: `{k}`", ephemeral=True)
            return

        new_title = title.strip() or row["title"]
        new_content = content.strip() or row["content"]
        new_tags = tags.strip() or (row["tags"] or "")
        new_arch = (archetype.strip().lower() or row["archetype"])
        new_fmt = (format.strip().lower() or row["format"])

        await con.execute(
            """UPDATE rulings SET title=$2, content=$3, tags=$4, archetype=$5, format=$6 WHERE key=$1;""",
            k, new_title, new_content, new_tags, new_arch, new_fmt
        )

    await interaction.response.send_message(f"✅ Modifié: `{k}`", ephemeral=True)

@bot.tree.command(name="ruling_delete", description="(Admin) Supprime un ruling.")
async def ruling_delete(interaction: discord.Interaction, key: str):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return
    k = norm_key(key)
    async with pool.acquire() as con:
        res = await con.execute("DELETE FROM rulings WHERE key=$1;", k)
    await interaction.response.send_message(f"🗑️ Supprimé: `{k}`", ephemeral=True)

@bot.tree.command(name="ruling_review", description="(Admin) Voir les suggestions en attente.")
async def ruling_review(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return
    async with pool.acquire() as con:
        rows = await con.fetch(
            "SELECT id, key, title, author_name, created_at FROM suggestions WHERE status='pending' ORDER BY id DESC LIMIT 10;"
        )
    if not rows:
        await interaction.response.send_message("Aucune suggestion en attente.", ephemeral=True)
        return

    lines = []
    for r in rows:
        lines.append(f"• ID **{r['id']}** — `{r['key']}` — {r['title']} (par {r['author_name']})")
    e = discord.Embed(title="🧾 Suggestions (pending)", description="\n".join(lines)[:4000])
    await interaction.response.send_message(embed=e, ephemeral=True)

@bot.tree.command(name="ruling_approve", description="(Admin) Valider une suggestion (copie en rulings).")
async def ruling_approve(interaction: discord.Interaction, suggestion_id: int):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return

    async with pool.acquire() as con:
        s = await con.fetchrow(
            "SELECT * FROM suggestions WHERE id=$1 AND status='pending';",
            suggestion_id
        )
        if not s:
            await interaction.response.send_message("❌ Suggestion introuvable ou déjà traitée.", ephemeral=True)
            return

        await con.execute(
            """INSERT INTO rulings(key, title, content, tags, archetype, format)
               VALUES($1,$2,$3,$4,$5,$6)
               ON CONFLICT (key) DO UPDATE
                 SET title=EXCLUDED.title, content=EXCLUDED.content, tags=EXCLUDED.tags,
                     archetype=EXCLUDED.archetype, format=EXCLUDED.format;""",
            s["key"], s["title"], s["content"], s["tags"], s["archetype"], s["format"]
        )
        await con.execute("UPDATE suggestions SET status='approved' WHERE id=$1;", suggestion_id)

    await interaction.response.send_message(f"✅ Suggestion approuvée et ajoutée: `{s['key']}`", ephemeral=True)

# ----------------------------
# Main
# ----------------------------
async def main():
    await startup()
    await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
