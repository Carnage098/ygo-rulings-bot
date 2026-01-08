import os
import json
import difflib
from typing import List, Dict, Any, Tuple, Optional

import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant (Railway > Variables).")

RULINGS_FILE = "rulings.json"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Cache en mémoire
RULINGS: List[Dict[str, Any]] = []


# -----------------------
# Helpers lecture/écriture
# -----------------------

def normalize_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalise un ruling. Retourne None si invalide."""
    if "key" not in item or "content" not in item:
        return None

    key = str(item["key"]).strip().lower()
    if not key:
        return None

    title = str(item.get("title", key)).strip() or key
    content = str(item.get("content", "")).strip()
    tags = item.get("tags", [])
    if isinstance(tags, str):
        # autorise "tag1, tag2"
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags = [str(t).strip().lower() for t in tags if str(t).strip()]

    return {
        "key": key,
        "title": title,
        "content": content,
        "tags": tags,
    }


def load_rulings() -> List[Dict[str, Any]]:
    """Charge rulings.json."""
    if not os.path.exists(RULINGS_FILE):
        # crée un fichier vide si absent
        with open(RULINGS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        return []

    with open(RULINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    out: List[Dict[str, Any]] = []
    if not isinstance(data, list):
        return out

    for raw in data:
        if not isinstance(raw, dict):
            continue
        norm = normalize_item(raw)
        if norm:
            out.append(norm)

    # dédupe par key (garde la première occurrence)
    seen = set()
    deduped = []
    for r in out:
        if r["key"] not in seen:
            seen.add(r["key"])
            deduped.append(r)
    return deduped


def save_rulings(rulings: List[Dict[str, Any]]) -> None:
    """Sauvegarde dans rulings.json."""
    with open(RULINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(rulings, f, ensure_ascii=False, indent=2)


def get_ruling_by_key(key: str) -> Optional[Dict[str, Any]]:
    k = key.strip().lower()
    for r in RULINGS:
        if r["key"] == k:
            return r
    return None


def upsert_ruling(item: Dict[str, Any]) -> str:
    """
    Ajoute ou remplace un ruling par key.
    Retourne "added" ou "updated".
    """
    key = item["key"]
    for i, r in enumerate(RULINGS):
        if r["key"] == key:
            RULINGS[i] = item
            return "updated"
    RULINGS.append(item)
    return "added"


def delete_ruling(key: str) -> bool:
    k = key.strip().lower()
    for i, r in enumerate(RULINGS):
        if r["key"] == k:
            RULINGS.pop(i)
            return True
    return False


# -----------------------
# Recherche & Embeds
# -----------------------

def search_rulings(query: str, limit: int = 5) -> Tuple[List[Dict[str, Any]], List[str]]:
    q = query.strip().lower()
    if not q:
        return [], []

    exact = [r for r in RULINGS if r["key"] == q]

    contains = []
    tag_matches = []
    title_matches = []
    for r in RULINGS:
        if r["key"] != q and (q in r["key"] or r["key"] in q):
            contains.append(r)
        elif q in r.get("title", "").lower():
            title_matches.append(r)
        elif any(q in t or t in q for t in r.get("tags", [])):
            tag_matches.append(r)

    seen = set()
    ordered = []
    for group in (exact, contains, title_matches, tag_matches):
        for r in group:
            if r["key"] not in seen:
                seen.add(r["key"])
                ordered.append(r)

    matches = ordered[:limit]

    keys = [r["key"] for r in RULINGS]
    suggestions = difflib.get_close_matches(q, keys, n=5, cutoff=0.55)

    return matches, suggestions


def make_embed(r: Dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=r.get("title", r["key"]),
        description=r.get("content", "")[:4000],  # sécurité
    )
    tags = r.get("tags", [])
    if tags:
        embed.add_field(name="Tags", value=", ".join(tags[:20]), inline=False)
    embed.set_footer(text=f"Key: {r['key']}")
    return embed


def is_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.user and interaction.user.guild_permissions.administrator)


# -----------------------
# Events
# -----------------------

@bot.event
async def on_ready():
    global RULINGS
    RULINGS = load_rulings()
    print(f"✅ Logged in as {bot.user} (id={bot.user.id})")
    print(f"✅ Loaded rulings: {len(RULINGS)}")

    try:
        synced = await bot.tree.sync()
        print(f"✅ Slash commands sync: {len(synced)}")
    except Exception as e:
        print("⚠️ Sync error:", e)


# -----------------------
# Slash commands (public)
# -----------------------

@bot.tree.command(name="ruling", description="Affiche le meilleur ruling correspondant (avec suggestions).")
@app_commands.describe(topic="Ex: damage step, miss timing, ash blossom")
async def ruling(interaction: discord.Interaction, topic: str):
    matches, suggestions = search_rulings(topic, limit=3)

    if not matches:
        msg = "Je n’ai rien trouvé dans ma base."
        if suggestions:
            msg += "\nSuggestions: " + ", ".join(f"`{s}`" for s in suggestions)
        await interaction.response.send_message(msg, ephemeral=True)
        return

    if len(matches) == 1:
        await interaction.response.send_message(embed=make_embed(matches[0]))
        return

    embed = make_embed(matches[0])
    others = "\n".join(f"• `{m['key']}` — {m.get('title','')}" for m in matches[1:])
    if others:
        embed.add_field(name="Autres résultats proches", value=others, inline=False)
    if suggestions:
        embed.add_field(name="Suggestions", value=", ".join(f"`{s}`" for s in suggestions), inline=False)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ruling_search", description="Liste des rulings qui correspondent (sans afficher tout le contenu).")
@app_commands.describe(query="Mot-clé à chercher")
async def ruling_search(interaction: discord.Interaction, query: str):
    matches, suggestions = search_rulings(query, limit=10)

    if not matches:
        msg = "Aucun résultat."
        if suggestions:
            msg += "\nSuggestions: " + ", ".join(f"`{s}`" for s in suggestions)
        await interaction.response.send_message(msg, ephemeral=True)
        return

    lines = []
    for r in matches:
        tags = r.get("tags", [])
        tag_str = f" (tags: {', '.join(tags[:4])})" if tags else ""
        lines.append(f"• `{r['key']}` — {r.get('title','')}{tag_str}")

    text = "\n".join(lines)
    if suggestions:
        text += "\n\nSuggestions: " + ", ".join(f"`{s}`" for s in suggestions)

    embed = discord.Embed(title=f"Résultats pour: {query}", description=text[:4000])
    await interaction.response.send_message(embed=embed, ephemeral=True)


# -----------------------
# Slash commands (admin)
# -----------------------

@bot.tree.command(name="ruling_reload", description="Recharge rulings.json (admin).")
async def ruling_reload(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return

    global RULINGS
    RULINGS = load_rulings()
    await interaction.response.send_message(f"✅ Rulings rechargés: {len(RULINGS)}", ephemeral=True)


@bot.tree.command(name="ruling_add", description="Ajoute un ruling dans la base (admin).")
@app_commands.describe(
    key="Identifiant (ex: ash blossom, damage step)",
    title="Titre affiché (ex: Ash Blossom & Joyous Spring)",
    content="Texte du ruling",
    tags="Tags séparés par des virgules (ex: negate, hand trap, chain)"
)
async def ruling_add(
    interaction: discord.Interaction,
    key: str,
    title: str,
    content: str,
    tags: Optional[str] = ""
):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return

    item = normalize_item({
        "key": key,
        "title": title,
        "content": content,
        "tags": tags or ""
    })
    if not item:
        await interaction.response.send_message("❌ Données invalides (key/content requis).", ephemeral=True)
        return

    existing = get_ruling_by_key(item["key"])
    if existing:
        await interaction.response.send_message(
            f"❌ La key `{item['key']}` existe déjà. Utilise `/ruling_edit`.",
            ephemeral=True
        )
        return

    RULINGS.append(item)
    save_rulings(RULINGS)
    await interaction.response.send_message(f"✅ Ajouté: `{item['key']}`", ephemeral=True)


@bot.tree.command(name="ruling_edit", description="Modifie un ruling existant (admin).")
@app_commands.describe(
    key="Key du ruling à modifier",
    title="Nouveau titre (laisse vide pour ne pas changer)",
    content="Nouveau contenu (laisse vide pour ne pas changer)",
    tags="Nouveaux tags (comma-separated). Laisse vide pour ne pas changer."
)
async def ruling_edit(
    interaction: discord.Interaction,
    key: str,
    title: Optional[str] = "",
    content: Optional[str] = "",
    tags: Optional[str] = ""
):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return

    r = get_ruling_by_key(key)
    if not r:
        await interaction.response.send_message(f"❌ Aucun ruling avec la key `{key}`.", ephemeral=True)
        return

    # Appliquer seulement ce qui est fourni
    if title and title.strip():
        r["title"] = title.strip()
    if content and content.strip():
        r["content"] = content.strip()
    if tags and tags.strip():
        r["tags"] = [t.strip().lower() for t in tags.split(",") if t.strip()]

    # Normalisation finale
    norm = normalize_item(r)
    if not norm:
        await interaction.response.send_message("❌ Modification invalide (résultat incohérent).", ephemeral=True)
        return

    # Remplacer proprement dans la liste
    upsert_ruling(norm)
    save_rulings(RULINGS)
    await interaction.response.send_message(f"✅ Modifié: `{norm['key']}`", ephemeral=True)


@bot.tree.command(name="ruling_delete", description="Supprime un ruling (admin).")
@app_commands.describe(key="Key à supprimer (ex: damage step)")
async def ruling_delete(interaction: discord.Interaction, key: str):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return

    ok = delete_ruling(key)
    if not ok:
        await interaction.response.send_message(f"❌ Aucun ruling avec la key `{key}`.", ephemeral=True)
        return

    save_rulings(RULINGS)
    await interaction.response.send_message(f"🗑️ Supprimé: `{key.strip().lower()}`", ephemeral=True)


@bot.tree.command(name="ruling_list", description="Liste toutes les keys (admin).")
async def ruling_list(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return

    keys = sorted([r["key"] for r in RULINGS])
    if not keys:
        await interaction.response.send_message("Base vide.", ephemeral=True)
        return

    # Discord limite la taille: on tronque si énorme
    text = "\n".join(f"• `{k}`" for k in keys)
    embed = discord.Embed(title=f"Rulings ({len(keys)})", description=text[:4000])
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(TOKEN)
