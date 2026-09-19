# ---------------------------------------------------------
# IMPORTS
# ---------------------------------------------------------
import random
import asyncio
import os
import html
import json
from pathlib import Path
from datetime import time, datetime
from zoneinfo import ZoneInfo
from discord import app_commands

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import aiohttp
from wordfreq import top_n_list

# Load environment variables
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)
TOKEN = os.getenv("DISCORD_TOKEN")

# Setup bot intents
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)

CHANNEL_ID = 1523280307204128868
NZ_TZ = ZoneInfo("Pacific/Auckland")
SCORES_FILE = "scores.json"

# Load recognizable 4-8 letter words for anagrams
ANAGRAM_WORDS = [
    w for w in top_n_list('en', 10000)
    if 4 <= len(w) <= 10 and w.isalpha()
]

hourly_times = [time(hour=h, minute=0, tzinfo=NZ_TZ) for h in range(24)]
daily_time = time(hour=9, minute=0, tzinfo=NZ_TZ)
# ---------------------------------------------------------
# Global State & Persistence
# ---------------------------------------------------------
active_questions = {
    "hourly": None,
    "daily": None
}

def load_scores():
    """Loads overall data structure from scores.json."""
    default_data = {
        "last_reset_month": datetime.now(NZ_TZ).month, 
        "users": {},
        "all_time_records": []  # List of dicts: [{"user_id": int, "name": str, "score": int, "month": str}]
    }
    if os.path.exists(SCORES_FILE):
        try:
            with open(SCORES_FILE, "r") as f:
                data = json.load(f)
                data["users"] = {int(k): v for k, v in data.get("users", {}).items()}
                data.setdefault("all_time_records", [])
                return data
        except json.JSONDecodeError:
            return default_data
    return default_data

def save_scores():
    """Saves global score_data to scores.json."""
    data_to_save = {
        "last_reset_month": score_data.get("last_reset_month", datetime.now(NZ_TZ).month),
        "users": {str(k): v for k, v in score_data["users"].items()},
        "all_time_records": score_data.get("all_time_records", [])
    }
    with open(SCORES_FILE, "w") as f:
        json.dump(data_to_save, f, indent=4)

score_data = load_scores()

# ---------------------------------------------------------
# Question generation
# ---------------------------------------------------------
def generate_arithmetic_question():
    """Generates one of four arithmetic questions and returns (prompt, correct_answer)."""
    op = random.choice(["multiplication", "division", "addition", "subtraction"])

    if op == "multiplication":
        a = random.randint(2, 99)
        b = random.randint(2, 99)
        return f"Solve: **{a} × {b}**", a * b

    elif op == "division":
        a = random.randint(2, 99)
        b = random.randint(2, 99)
        product = a * b
        return f"Solve: **{product} ÷ {b}**", a

    elif op == "addition":
        a = random.randint(1, 9999)
        b = random.randint(1, 9999)
        return f"Solve: **{a} + {b}**", a + b

    elif op == "subtraction":
        a = random.randint(1, 9999)
        b = random.randint(1, 9999)
        high, low = max(a, b), min(a, b)
        return f"Solve: **{high} - {low}**", high - low

def generate_anagram_question():
    word = random.choice(ANAGRAM_WORDS).lower()
    letters = list(word)
    scrambled = "".join(letters)
    
    # Keep shuffling until scrambled word differs from original
    while scrambled == word and len(word) > 1:
        random.shuffle(letters)
        scrambled = "".join(letters)

    embed = discord.Embed(
        title="🔤 Anagram Challenge",
        description=f"Unscramble the word: **{scrambled.lower()}**\n\n*First person to answer correctly wins **10 points**!*",
        color=discord.Color.purple()
    )
    
    # Returns (embed, answer_string)
    return embed, word

def generate_question():
    question_type = random.choice(["math", "anagram"])
    
    if question_type == "math":
        prompt, answer = generate_arithmetic_question()
        embed = discord.Embed(
            title="🧮 Speed Math Challenge",
            description=f"{prompt}\n\n*First person to answer correctly wins **10 points**!*",
            color=discord.Color.blue()
        )
        return embed, str(answer).lower()
    else:
        # generate_anagram_question already returns (embed, answer)
        return generate_anagram_question()

async def generate_trivia_question():
    """Fetches a random trivia question from OpenTDB."""
    url = "https://opentdb.com/api.php?amount=1&type=multiple"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data["results"]:
                    item = data["results"][0]
                    
                    # Clean up HTML entities in text (e.g., &quot; -> ")
                    question = html.unescape(item["question"])
                    correct_answer = html.unescape(item["correct_answer"])
                    category = html.unescape(item["category"])

                    embed = discord.Embed(
                        title=f"🌟 Daily Trivia Challenge ({category})",
                        description=f"**{question}**\n\n*First person to type the exact answer wins **20 points**!*",
                        color=discord.Color.gold()
                    )
                    return embed, correct_answer.lower()
                    
    # Fallback if API is unreachable
    embed = discord.Embed(
        title="🌟 Daily Trivia Challenge",
        description="**What is the capital of France?**\n\n*Worth **20 points**!*",
        color=discord.Color.gold()
    )
    return embed, "paris"

# ---------------------------------------------------------
# Hourly Loop 
# ---------------------------------------------------------
@tasks.loop(time=hourly_times)
async def hourly_question_check():
    global active_questions
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # Safety clear for any lingering hourly question
    active_questions["hourly"] = None

    # 75% chance to spawn a new hourly challenge (10 points)
    if random.random() < 0.75:
        # Removed 'await' since generate_question() is synchronous
        embed, answer = generate_question()
        active_questions["hourly"] = {"answer": str(answer).lower(), "points": 10}
        await channel.send(embed=embed)

        # Wait 30 minutes before expiring
        await asyncio.sleep(1800)

        # Only run timeout embed if the question remains unanswered
        if active_questions["hourly"] is not None:
            embed = discord.Embed(
                title="⏰ Time's Up!",
                description=(
                    f"Nobody guessed the hourly answer in time.\n\n"
                    f"The correct answer was: **{active_questions['hourly']['answer']}**"
                ),
                color=discord.Color.red()
            )
            await channel.send(embed=embed)
            active_questions["hourly"] = None

@hourly_question_check.before_loop
async def before_hourly_check():
    await bot.wait_until_ready()

# ---------------------------------------------------------
# Daily Loop 
# ---------------------------------------------------------
@tasks.loop(time=daily_time)
async def daily_trivia_check():
    global active_questions
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # Clear previous unanswered daily question
    if active_questions["daily"] is not None:
        active_questions["daily"] = None

    # Fetch daily trivia question (20 points)
    embed, answer = await generate_trivia_question()
    active_questions["daily"] = {"answer": answer, "points": 20}
    await channel.send(embed=embed)

    # Wait 3 hours (10,800 seconds)
    await asyncio.sleep(3 * 3600)

    # Expire daily question after 3 hours if still active
    if active_questions["daily"] is not None:
        embed = discord.Embed(
            title="⏰ Time's Up!",
            description=(
                f"⏰ **3 Hours Expired!** Time is up for today's Daily Trivia challenge.\n"
                f"The correct answer was: **{active_questions['daily']['answer']}**"
            ),
            color=discord.Color.red()
        )
        await channel.send(embed=embed)
        active_questions["daily"] = None

@daily_trivia_check.before_loop
async def before_daily_check():
    await bot.wait_until_ready()

# ---------------------------------------------------------
# Monthly loop
# ---------------------------------------------------------
@tasks.loop(hours=1)
async def monthly_reset_check():
    global score_data
    now = datetime.now(NZ_TZ)
    current_month = now.month
    stored_month = score_data.get("last_reset_month", current_month)

    if current_month != stored_month:
        channel = bot.get_channel(CHANNEL_ID)
        users = score_data["users"]

        if users:
            # 1. Crown the monthly winner
            winner_id = max(users, key=lambda u: users[u].get("score", 0))
            winner_data = users[winner_id]

            if winner_data.get("score", 0) > 0:
                winner_data["monthly_wins"] = winner_data.get("monthly_wins", 0) + 1
                if channel:
                    await channel.send(
                        f"🎉 **MONTHLY RESET!** Congratulations to <@{winner_id}> for winning this month's leaderboard with "
                        f"**{winner_data['score']}** points! They have gained **+1 Monthly Win**! 👑"
                    )

            # 2. Update "Hall of Fame / Best of the Best" record list
            records = score_data.get("all_time_records", [])
            month_label = now.strftime("%b %Y")  # e.g., "Sep 2026"

            for uid, udata in users.items():
                pts = udata.get("score", 0)
                if pts > 0:
                    records.append({
                        "user_id": uid,
                        "name": udata.get("name", "Unknown"),
                        "score": pts,
                        "month": month_label
                    })

            # Sort all historical season scores descending and keep top 5
            records.sort(key=lambda x: x["score"], reverse=True)
            score_data["all_time_records"] = records[:5]

        # 3. Reset all user scores for the new season
        for uid in users:
            users[uid]["score"] = 0

        score_data["last_reset_month"] = current_month
        save_scores()

@monthly_reset_check.before_loop
async def before_monthly_check():
    await bot.wait_until_ready()

# ---------------------------------------------------------
# Bot events and commands
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    if not hourly_question_check.is_running():
        hourly_question_check.start()
        
    if not daily_trivia_check.is_running():
        daily_trivia_check.start()

    if not monthly_reset_check.is_running():
        monthly_reset_check.start()

@bot.event
async def setup_hook():
    # Registers slash commands globally (can take a few minutes to show up across Discord)
    await bot.tree.sync()

@bot.event
async def on_message(message):
    global active_questions, score_data

    if message.author.bot:
        return

    if message.channel.id == CHANNEL_ID:
        user_guess = message.content.strip().lower()

        for q_type in ["daily", "hourly"]:
            q_data = active_questions.get(q_type)

            if q_data and user_guess == q_data["answer"]:
                user_id = message.author.id
                points_awarded = q_data["points"]
                users = score_data["users"]

                # Get existing user dict or create default
                user_record = users.get(user_id, {"name": str(message.author), "score": 0, "monthly_wins": 0})
                if isinstance(user_record, int):
                    user_record = {"name": str(message.author), "score": user_record, "monthly_wins": 0}

                user_record["score"] = user_record.get("score", 0) + points_awarded
                user_record["name"] = str(message.author)
                
                users[user_id] = user_record
                save_scores()

                await message.reply(
                    f"🎉 {message.author.mention} has received {points_awarded} points for the answer **{q_data['answer']}**!",
                    mention_author=True
                )
                active_questions[q_type] = None
                break

    await bot.process_commands(message)

@bot.tree.command(name="test", description="Spawn a test quiz question")
@app_commands.choices(question_type=[
    app_commands.Choice(name="Math", value="math"),
    app_commands.Choice(name="Anagram", value="anagram"),
    app_commands.Choice(name="Trivia", value="trivia")
])
async def test(interaction: discord.Interaction, question_type: str = None):
    global active_questions

    # 1. Acknowledge Discord immediately so it doesn't time out
    await interaction.response.defer()

    if question_type == "trivia":
        embed, answer = await generate_trivia_question()
        points = 20
        target_slot = "daily"
    elif question_type == "math":
        prompt, ans = generate_arithmetic_question()
        embed = discord.Embed(
            title="🧮 Speed Math Challenge",
            description=f"{prompt}\n\n*First person to answer correctly wins **10 points**!*",
            color=discord.Color.blue()
        )
        answer = str(ans).lower()
        points = 10
        target_slot = "hourly"
    elif question_type == "anagram":
        embed, answer = generate_anagram_question()
        points = 10
        target_slot = "hourly"
    else:
        chosen_type = random.choice(["math", "anagram", "trivia"])
        if chosen_type == "trivia":
            embed, answer = await generate_trivia_question()
            points = 20
            target_slot = "daily"
        else:
            embed, answer = generate_question()
            points = 10
            target_slot = "hourly"

    active_questions[target_slot] = {"answer": str(answer).lower(), "points": points}
    
    # 2. Use followup.send instead of ctx.send
    await interaction.followup.send(
        f"🧪 **Test Question Spawned (Slot: `{target_slot}`, Points: `{points}`)**", 
        embed=embed
    )

# Command to check individual user points
@bot.tree.command(name="points", description="Check your current quiz points")
async def points(interaction: discord.Interaction):
    users = score_data["users"]
    user_record = users.get(interaction.user.id, {"score": 0, "monthly_wins": 0})
    
    # Handle integer fallback if user data was recorded prior to the JSON dictionary update
    if isinstance(user_record, int):
        score = user_record
        wins = 0
    else:
        score = user_record.get("score", 0)
        wins = user_record.get("monthly_wins", 0)

    embed = discord.Embed(
        title=f"🏆 {interaction.user.display_name}'s Stats",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="Current Points", value=f"**{score}** pts", inline=True)
    embed.add_field(name="Monthly Titles", value=f"**{wins}** 👑", inline=True)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="info", description="Learn how the bot actually works")
async def info(interaction: discord.Interaction):
    embed = discord.Embed(
        title="ℹ️ QuizBot Help & Overview",
        description="Welcome! Here is a breakdown of how challenges and scoring work:",
        color=discord.Color.teal()
    )

    embed.add_field(
        name="⏱️ Hourly Challenges",
        value="Every hour, there's a 75% chance to spawn a Math or Anagram challenge. First correct guess wins **10 points**!",
        inline=False
    )
    embed.add_field(
        name="🌟 Daily Trivia",
        value="Posted every day at **9:00 AM NZT**. You have **3 hours** to guess correctly for **20 points**!",
        inline=False
    )
    embed.add_field(
        name="👑 Monthly Reset",
        value="At midnight on the 1st of each month, the top player gets **+1 Monthly Win**, and current season scores reset to zero.",
        inline=False
    )
    
    embed.set_footer(text="Use /leaderboard to check standings or /points to check your score.")

    await interaction.response.send_message(embed=embed)
# ---------------------------------------------------------
# Leaderboards
# ---------------------------------------------------------
class LeaderboardView(discord.ui.View):
    def __init__(self, users, records):
        super().__init__(timeout=60)
        self.users = users
        self.records = records

    @discord.ui.select(
        placeholder="Choose a leaderboard to view...",
        options=[
            discord.SelectOption(label="Current Season Leaderboard", value="current", emoji="🏆"),
            discord.SelectOption(label="Monthly Champions Leaderboard", value="monthly", emoji="👑"),
            discord.SelectOption(label="Best of the Best (Hall of Fame)", value="hall_of_fame", emoji="⭐"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        embed = discord.Embed(color=discord.Color.gold())

        if select.values[0] == "current":
            embed.title = "🏆 Current Season Leaderboard"
            sorted_users = sorted(
                self.users.items(),
                key=lambda x: x[1].get("score", 0) if isinstance(x[1], dict) else x[1],
                reverse=True
            )
            desc = ""
            for rank, (user_id, data) in enumerate(sorted_users, start=1):
                pts = data.get("score", 0) if isinstance(data, dict) else data
                if pts > 0:
                    medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"**#{rank}**"
                    desc += f"{medal} <@{user_id}> — **{pts}** pts\n"
            embed.description = desc if desc else "No points scored this month yet!"

        elif select.values[0] == "monthly":
            embed.title = "👑 Monthly Champions Leaderboard"
            sorted_users = sorted(
                self.users.items(),
                key=lambda x: x[1].get("monthly_wins", 0) if isinstance(x[1], dict) else 0,
                reverse=True
            )
            desc = ""
            for rank, (user_id, data) in enumerate(sorted_users, start=1):
                wins = data.get("monthly_wins", 0) if isinstance(data, dict) else 0
                if wins > 0:
                    medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"**#{rank}**"
                    desc += f"{medal} <@{user_id}> — **{wins}** monthly win(s)\n"
            embed.description = desc if desc else "No monthly champions crowned yet!"

        else:
            embed.title = "⭐ Best of the Best (Top 5 All-Time Seasons)"
            desc = ""
            for rank, rec in enumerate(self.records, start=1):
                medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"**#{rank}**"
                desc += f"{medal} <@{rec['user_id']}> — **{rec['score']}** pts *({rec.get('month', 'Past Season')})*\n"
            
            embed.description = desc if desc else "No seasonal records recorded yet! Records compile at the end of each month."

        await interaction.response.edit_message(embed=embed, view=self)

@bot.tree.command(name="leaderboard", description="View current season, monthly champions, and all-time record leaderboards")
async def leaderboard(interaction: discord.Interaction):
    users = score_data["users"]
    records = score_data.get("all_time_records", [])

    if not users and not records:
        await interaction.response.send_message("📊 The leaderboard is currently empty!")
        return

    embed = discord.Embed(
        title="📊 QuizBot Leaderboards",
        description="Select an option below to view current points, monthly wins, or all-time high scores!",
        color=discord.Color.blue()
    )
    view = LeaderboardView(users, records)
    
    await interaction.response.send_message(embed=embed, view=view)

bot.run(TOKEN)