import random
import asyncio
import os
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from wordfreq import top_n_list
import html
import aiohttp

from datetime import time
from zoneinfo import ZoneInfo

# ---------------------------------------------------------
# SETUP
# ---------------------------------------------------------

# Import settings
NZ_TZ = ZoneInfo("Pacific/Auckland")
hourly_times = [time(hour=h, minute=0, tzinfo=NZ_TZ) for h in range(24)]

ANAGRAM_WORDS = [
    w.lower() for w in top_n_list('en', 10000)
    if 3 <= len(w) <= 10 and w.isalpha()
]

# Load environment variables explicitly from the script's directory
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)
TOKEN = os.getenv("DISCORD_TOKEN")

# Setup bot intents
intents = discord.Intents.default()
intents.message_content = True  # Required to read chat messages for answers

# Initialized bot with '#' and '/' prefixes
bot = commands.Bot(command_prefix=["#", "/"], intents=intents)

CHANNEL_ID = 1523280307204128868

# Tracking states
active_question = None  # Holds dict: {"answer": str, "prompt": str}
user_scores = {}        # Stores user_id: score

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
# 1Hourly Loop (Runs on the dot every hour, e.g., 1:00, 2:00)
# ---------------------------------------------------------
hourly_times = [time(hour=h, minute=0, tzinfo=NZ_TZ) for h in range(24)]

@tasks.loop(time=hourly_times)
async def hourly_question_check():
    global active_question

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # Clear previous unanswered question
    if active_question is not None:
        await channel.send(
            f"⏰ **Time's up!** Nobody guessed the previous answer in time.\n"
            f"The correct answer was: **{active_question['answer']}**"
        )
        active_question = None

    # 66% chance roll
    if random.random() < 0.66:
        embed, answer = generate_question()
        active_question = {"answer": answer, "points": 10}
        await channel.send(embed=embed)

@hourly_question_check.before_loop
async def before_hourly_check():
    await bot.wait_until_ready()
# ---------------------------------------------------------
# 2Daily Loop (Runs at exactly 9:00 AM NZT every day)
# ---------------------------------------------------------
daily_time = time(hour=9, minute=0, tzinfo=NZ_TZ)

@tasks.loop(time=daily_time)
async def daily_trivia_check():
    global active_question

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # Clear previous unanswered question
    if active_question is not None:
        await channel.send(
            f"⏰ **Time's up!** Nobody guessed the previous answer in time.\n"
            f"The correct answer was: **{active_question['answer']}**"
        )
        active_question = None

    # Generate daily trivia worth 20 points
    embed, answer = await generate_trivia_question()
    active_question = {"answer": answer, "points": 20}
    await channel.send(embed=embed)

@daily_trivia_check.before_loop
async def before_daily_check():
    await bot.wait_until_ready()
# ---------------------------------------------------------
# Start Both Loops in on_ready
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
    global active_question

    if message.author.bot:
        return

    if active_question and message.channel.id == CHANNEL_ID:
        user_guess = message.content.strip().lower()

        if user_guess == active_question["answer"]:
            user_id = message.author.id
            points_awarded = active_question.get("points", 10)  # Default to 10 if not set
            user_scores[user_id] = user_scores.get(user_id, 0) + points_awarded

            await message.reply(
                f"🎉 {message.author.mention} has received {points_awarded} points for the answer **{active_question['answer']}**!",
                mention_author=True
            )
            active_question = None

    await bot.process_commands(message)

# ---------------------------------------------------------
# BOT COMMANDS
# ---------------------------------------------------------

# Command to force-trigger a test question
@bot.command()
async def test(ctx):
    global active_question
    embed, answer = generate_question()
    active_question = {"answer": answer}
    
    # Send as embed instead of raw text
    await ctx.send(embed=embed)


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