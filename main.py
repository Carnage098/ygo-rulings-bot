import os
import discord
from discord.ext import commands
from discord import app_commands

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant (Railway > Variables).")

# --- Choisis ton mode ---
USE_PREFIX_COMMANDS = False  # True si tu veux !ruling (nécessite Message Content Intent)

intents = discord.Intents.default()
if USE_PREFIX_COMMANDS:
    intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Petite base de rulings (tu peux l’agrandir)
RULINGS = {
    "damage step": "Damage Step: fenêtre très restrictive. ATK/DEF modifs et certains contres/effets seulement.",
    "miss timing": "Miss timing: souvent avec 'When... you can'. Si l’événement n’est pas la dernière chose arrivée, ça peut rater.",
    "ash blossom": "Ash Blossom: peut annuler un effet qui ajoute du Deck à la main, envoie du Deck au GY, ou SS depuis le Deck."
}

def find_ruling(query: str) -> str | None:
    q = query.strip().lower()
    if q in RULINGS:
        return RULINGS[q]
    # recherche partielle
    for k, v in RULINGS.items():
        if q in k or k in q:
            return v
    return None

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (id={bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"✅ Slash commands sync: {len(synced)}")
    except Exception as e:
        print("⚠️ Sync error:", e)

# --- Slash command: /ruling ---
@bot.tree.command(name="ruling", description="Donne une explication rapide d'un concept ou d'une carte.")
@app_commands.describe(topic="Ex: damage step, miss timing, ash blossom")
async def ruling_slash(interaction: discord.Interaction, topic: str):
    ans = find_ruling(topic)
    if not ans:
        await interaction.response.send_message(
            "Je n’ai pas trouvé ce ruling dans ma base. Essaie un autre mot-clé.",
            ephemeral=True
        )
        return

    embed = discord.Embed(title=f"Ruling: {topic}", description=ans)
    await interaction.response.send_message(embed=embed)

# --- Commande préfixe optionnelle: !ruling ---
@bot.command(name="ruling")
async def ruling_prefix(ctx: commands.Context, *, topic: str):
    ans = find_ruling(topic)
    if not ans:
        await ctx.send("Je n’ai pas trouvé ce ruling dans ma base. Essaie un autre mot-clé.")
        return
    await ctx.send(f"**Ruling: {topic}**\n{ans}")

bot.run(TOKEN)
