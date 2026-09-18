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
    if 3 <= len(w) <= 10 and w.isalpha()
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
    default_data = {"last_reset_month": datetime.now(NZ_TZ).month, "users": {}}
    if os.path.exists(SCORES_FILE):
        try:
            with open(SCORES_FILE, "r") as f:
                data = json.load(f)
                # Convert JSON string keys back to integer Discord user IDs
                data["users"] = {int(k): v for k, v in data.get("users", {}).items()}
                return data
        except json.JSONDecodeError:
            return default_data
    return default_data

def save_scores():
    """Saves global score_data to scores.json."""
    data_to_save = {
        "last_reset_month": score_data.get("last_reset_month", datetime.now(NZ_TZ).month),
        "users": {str(k): v for k, v in score_data["users"].items()}
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
    """Selects a word, shuffles its letters, and returns (prompt, original_word)."""
    word = random.choice(ANAGRAM_WORDS).lower()
    letters = list(word)

    scrambled = "".join(letters)
    while scrambled == word and len(word) > 1:
        random.shuffle(letters)
        scrambled = "".join(letters)

    return f"Unscramble the word: **{scrambled.lower()}**", word

def generate_question():
    """Randomly chooses a question type and returns a styled discord.Embed and the answer string."""
    question_type = random.choice(["math", "anagram"])
    
    if question_type == "math":
        prompt, answer = generate_arithmetic_question()
        title = "**Math Challenge**"
        color = discord.Color.blue()
    else:
        prompt, answer = generate_anagram_question()
        title = "**Anagram Challenge**"
        color = discord.Color.purple()

    # Create the boxed window (Embed)
    embed = discord.Embed(
        title=title,
        description=f"{prompt}\n\n*First person to answer correctly wins **10 points**!*",
        color=color
    )
    
    return embed, str(answer).lower()

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

    # Clear unanswered hourly question from the previous hour
    if active_questions["hourly"] is not None:
        await channel.send(
            f"⏰ **Time's up!** Nobody guessed the hourly answer in time.\n"
            f"The correct answer was: **{active_questions['hourly']['answer']}**"
        )
        active_questions["hourly"] = None

    # 66% chance to spawn a new hourly challenge (10 points)
    if random.random() < 0.66:
        embed, answer = generate_question()
        active_questions["hourly"] = {"answer": answer, "points": 10}
        await channel.send(embed=embed)

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
        await channel.send(
            f"⏰ **3 Hours Expired!** Time is up for today's Daily Trivia challenge.\n"
            f"The correct answer was: **{active_questions['daily']['answer']}**"
        )
        active_questions["daily"] = None

@daily_trivia_check.before_loop
async def before_daily_check():
    await bot.wait_until_ready()

# ---------------------------------------------------------
# Monthly loop
# ---------------------------------------------------------
@tasks.loop(hours=1)
async def monthly_reset_check():
    global score_data, user_scores
    
    now = datetime.now(NZ_TZ)
    current_month = now.month
    stored_month = score_data.get("last_reset_month", current_month)

    # Trigger reset if a new month has arrived
    if current_month != stored_month:
        channel = bot.get_channel(CHANNEL_ID)

        if user_scores:
            # Find the top player with the highest current score
            winner_id = max(user_scores, key=lambda u: user_scores[u].get("score", 0))
            winner_data = user_scores[winner_id]

            if winner_data.get("score", 0) > 0:
                # Increment monthly wins counter
                winner_data["monthly_wins"] = winner_data.get("monthly_wins", 0) + 1
                
                if channel:
                    await channel.send(
                        f"🎉 **MONTHLY RESET!** Congratulations to <@{winner_id}> for winning this month's leaderboard with "
                        f"**{winner_data['score']}** points! They have gained **+1 Monthly Win**! 👑"
                    )

        # Reset all current season scores to 0
        for uid in user_scores:
            user_scores[uid]["score"] = 0

        # Update last reset month and save to file
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

# Command to force-trigger a test question
# Usage: #test (random), #test math, #test anagram, or #test trivia
@bot.command()
async def test(ctx, question_type: str = None):
    global active_questions
    
    # Normalize input
    if question_type:
        question_type = question_type.lower().strip()

    # Determine question type
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
        # Pick randomly if no specific type (or an invalid type) is provided
        chosen_type = random.choice(["math", "anagram", "trivia"])
        if chosen_type == "trivia":
            embed, answer = await generate_trivia_question()
            points = 20
            target_slot = "daily"
        else:
            embed, answer = generate_question()
            points = 10
            target_slot = "hourly"

    # Save to the active dictionary and notify in chat
    active_questions[target_slot] = {"answer": str(answer).lower(), "points": points}
    
    await ctx.send(f"🧪 **Test Question Spawned (Slot: `{target_slot}`, Points: `{points}`)**", embed=embed)

# Command to check individual user points
@bot.command()
async def points(ctx):
    users = score_data["users"]
    user_record = users.get(ctx.author.id, {"score": 0})
    score = user_record["score"] if isinstance(user_record, dict) else user_record
    await ctx.send(f"{ctx.author.mention}, you currently have **{score}** points!")

# ---------------------------------------------------------
# Leaderboards
# ---------------------------------------------------------
class LeaderboardView(discord.ui.View):
    def __init__(self, user_scores):
        super().__init__(timeout=60)
        self.user_scores = user_scores

    @discord.ui.select(
        placeholder="Choose a leaderboard to view...",
        options=[
            discord.SelectOption(label="Current Season Leaderboard", value="current", emoji="🏆"),
            discord.SelectOption(label="Monthly Champions Leaderboard", value="monthly", emoji="👑"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        embed = discord.Embed(color=discord.Color.gold())
        
        if select.values[0] == "current":
            embed.title = "🏆 Current Season Leaderboard"
            sorted_users = sorted(
                self.user_scores.items(),
                key=lambda x: x[1].get("score", 0),
                reverse=True
            )
            desc = ""
            for rank, (user_id, data) in enumerate(sorted_users, start=1):
                pts = data.get("score", 0)
                if pts > 0:
                    medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"**#{rank}**"
                    desc += f"{medal} <@{user_id}> — **{pts}** pts\n"
            
            embed.description = desc if desc else "No points scored this month yet!"

        else:
            embed.title = "👑 Monthly Champions Leaderboard"
            sorted_users = sorted(
                self.user_scores.items(),
                key=lambda x: x[1].get("monthly_wins", 0),
                reverse=True
            )
            desc = ""
            for rank, (user_id, data) in enumerate(sorted_users, start=1):
                wins = data.get("monthly_wins", 0)
                if wins > 0:
                    medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"**#{rank}**"
                    desc += f"{medal} <@{user_id}> — **{wins}** monthly win(s)\n"
            
            embed.description = desc if desc else "No monthly champions crowned yet!"

        await interaction.response.edit_message(embed=embed, view=self)

@bot.command(aliases=["lb"])
async def scoreboard(ctx):
    users = score_data["users"]
    if not users:
        await ctx.send("📊 The leaderboard is currently empty!")
        return

    embed = discord.Embed(
        title="📊 Quiz Leaderboards",
        description="Select an option below to view either the current month's points or past monthly wins!",
        color=discord.Color.blue()
    )
    view = LeaderboardView(users)
    await ctx.send(embed=embed, view=view)

bot.run(TOKEN)