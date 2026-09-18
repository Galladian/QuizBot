import random
import asyncio
import os
import json
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from wordfreq import top_n_list
import html
import aiohttp

from datetime import time
from zoneinfo import ZoneInfo

def load_scores():
    """Loads scores from scores.json on startup."""
    if os.path.exists(SCORES_FILE):
        try:
            with open(SCORES_FILE, "r") as f:
                data = json.load(f)
                # Convert string keys from JSON back to integer Discord IDs
                return {int(k): v for k, v in data.items()}
        except json.JSONDecodeError:
            return {}
    return {}

def save_scores():
    """Saves current scores dictionary to scores.json."""
    with open(SCORES_FILE, "w") as f:
        # Convert integer keys to strings for valid JSON encoding
        json.dump({str(k): v for k, v in user_scores.items()}, f, indent=4)

# ---------------------------------------------------------
# SETUP
# ---------------------------------------------------------

# Import settings
NZ_TZ = ZoneInfo("Pacific/Auckland")
hourly_times = [time(hour=h, minute=0, tzinfo=NZ_TZ) for h in range(24)]
daily_time = time(hour=9, minute=0, tzinfo=NZ_TZ)

ANAGRAM_WORDS = [
    w.lower() for w in top_n_list('en', 10000)
    if 3 <= len(w) <= 10 and w.isalpha()
]

# Load environment variables explicitly from the script's directory
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)
TOKEN = os.getenv("DISCORD_TOKEN")

SCORES_FILE = "scores.json"

# Setup bot intents
intents = discord.Intents.default()
intents.message_content = True  # Required to read chat messages for answers

# Initialized bot with '#' and '/' prefixes
bot = commands.Bot(command_prefix=["#", "/"], intents=intents)

CHANNEL_ID = 1523280307204128868

# Tracking states
active_questions = {
    "hourly": None,
    "daily": None
} 
user_scores = load_scores() 
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

# ---------------------------------------------------------
# Hourly Loop (Runs on the dot every hour, e.g., 1:00, 2:00)
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
# Daily Loop (Runs at exactly 9:00 AM NZT every day)
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
# BOT COMMANDS
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    
    if not hourly_question_check.is_running():
        hourly_question_check.start()
        
    if not daily_trivia_check.is_running():
        daily_trivia_check.start()

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.channel.id == CHANNEL_ID:
        user_guess = message.content.strip().lower()

        for q_type in ["daily", "hourly"]:
            q_data = active_questions.get(q_type)
            
            if q_data and user_guess == q_data["answer"]:
                user_id = message.author.id
                points_awarded = q_data["points"]
                
                # Retrieve current score (supporting both old integer format and new dictionary format)
                current_data = user_scores.get(user_id, {"name": str(message.author), "score": 0})
                if isinstance(current_data, int):
                    current_data = {"name": str(message.author), "score": current_data}

                # Update score and display name
                current_data["score"] += points_awarded
                current_data["name"] = str(message.author)  # e.g., "andrew_dev"
                
                user_scores[user_id] = current_data
                save_scores()  # Persist to JSON file

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
    score = user_scores.get(ctx.author.id, 0)
    await ctx.send(f"{ctx.author.mention}, you currently have **{score}** points!")


# Command to display the top scores
@bot.command(aliases=["lb"])
async def leaderboard(ctx):
    if not user_scores:
        await ctx.send("📊 The leaderboard is currently empty! Answer a question to get on the board.")
        return

    sorted_scores = sorted(user_scores.items(), key=lambda item: item[1], reverse=True)

    embed = discord.Embed(
        title="🏆 QuizBot Leaderboard",
        color=discord.Color.gold()
    )

    description = ""
    for rank, (user_id, score) in enumerate(sorted_scores, start=1):
        if rank == 1:
            medal = "🥇"
        elif rank == 2:
            medal = "🥈"
        elif rank == 3:
            medal = "🥉"
        else:
            medal = f"**#{rank}**"

        description += f"{medal} <@{user_id}> — **{score}** points\n"

    embed.description = description
    await ctx.send(embed=embed)


bot.run(TOKEN)