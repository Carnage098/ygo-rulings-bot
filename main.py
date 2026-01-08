import os
import json
import difflib
from typing import List, Dict, Any, Tuple

import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant (Railway > Variables).")

RULINGS_FILE = "rulings.json"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)  # prefix inutile ici mais ok

# Cache en mémoire (rechargé au démarrage)
RULINGS: List[Dict[str, Any]] = []


def load_rulings() -> List[Dict[str, Any]]:
    """Charge rulings.json."""
    if not os.path.exists(RULINGS_FILE):
        return []
    with open(RULINGS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Normalisation
    out = []
    for item in data:
        if "key" not in item or "content" not in item:
            continue
        item["key"] = str(item["key"]).strip().lower()
        item["title"] = str(item.get("title", item["key"])).strip()
        item["tags"] = [str(t).strip().lower() for t in item.get("tags", [])]
        out.append(item)
    return out


def search_rulings(query: str, limit: int = 5) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Retourne (matches, suggestions_keys).
    - matches: résultats triés (exact > contient > tags)
    - suggestions: keys proches (diff lib)
    """
    q = query.strip().lower()
    if not q:
        return [], []

    exact = [r for r in RULINGS if r["key"] == q]

    contains = []
    tag_matches = []
    for r in RULINGS:
        if r["key"] != q and (q in r["key"] or r["key"] in q):
            contains.append(r)
        elif q in r.get("title", "").lower():
            contains.append(r)
        elif any(q in t or t in q for t in r.get("tags", [])):
            tag_matches.append(r)

    # Dédupe en gardant l'ordre de priorité
    seen = set()
    ordered = []
    for group in (exact, contains, tag_matches):
        for r in group:
            if r["key"] not in seen:
                seen.add(r["key"])
                ordered.append(r)

    matches = ordered[:limit]

    # Suggestions proches si pas assez de matches
    keys = [r["key"] for r in RULINGS]
    suggestions = difflib.get_close_matches(q, keys, n=5, cutoff=0.55)

    return matches, suggestions


def make_embed(r: Dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title=r.get("title", r["key"]),
        description=r.get("content", ""),
    )
    tags = r.get("tags", [])
    if tags:
        embed.add_field(name="Tags", value=", ".join(tags[:15]), inline=False)
    embed.set_footer(text=f"Key: {r['key']}")
    return embed


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

    # Si un seul match, on affiche direct
    if len(matches) == 1:
        await interaction.response.send_message(embed=make_embed(matches[0]))
        return

    # Plusieurs matches: on affiche le meilleur + liste des autres
    embed = make_embed(matches[0])
    others = "\n".join(f"• `{m['key']}` — {m.get('title','')}" for m in matches[1:])
    if others:
        embed.add_field(name="Autres résultats proches", value=others, inline=False)

    if suggestions:
        embed.add_field(
            name="Suggestions",
            value=", ".join(f"`{s}`" for s in suggestions),
            inline=False,
        )

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

    embed = discord.Embed(title=f"Résultats pour: {query}", description=text)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="ruling_reload", description="Recharge rulings.json (admin).")
async def ruling_reload(interaction: discord.Interaction):
    # Simple protection: admin uniquement
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Commande réservée aux admins.", ephemeral=True)
        return

    global RULINGS
    RULINGS = load_rulings()
    await interaction.response.send_message(f"✅ Rulings rechargés: {len(RULINGS)}", ephemeral=True)


bot.run(TOKEN)
