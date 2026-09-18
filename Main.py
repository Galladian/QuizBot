import random
import asyncio
import os
from pathlib import Path

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from wordfreq import top_n_list

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

ANAGRAM_WORDS = [
    w.lower() for w in top_n_list('en', 10000)
    if 3 <= len(w) <= 10 and w.isalpha()
]


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
    """Randomly chooses between a math problem or an anagram challenge."""
    question_type = random.choice(["math", "anagram"])
    if question_type == "math":
        return generate_arithmetic_question()
    else:
        return generate_anagram_question()


@tasks.loop(hours=1)
async def hourly_question_check():
    global active_question

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # 1. Clear unanswered question from previous hour
    if active_question is not None:
        await channel.send(
            f"⏰ **Time's up!** Nobody guessed the correct answer in time.\n"
            f"The correct answer was: **{active_question['answer']}**"
        )
        active_question = None

    # 2. 66% chance to spawn a new question
    if random.random() < 0.66:
        prompt, answer = generate_question()
        active_question = {"answer": str(answer).lower(), "prompt": prompt}
        await channel.send(
            f"{prompt} \n (First to answer gets 10 points)"
        )


@hourly_question_check.before_loop
async def before_hourly_check():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    if not hourly_question_check.is_running():
        hourly_question_check.start()


@bot.event
async def on_message(message):
    global active_question

    # Ignore messages sent by bots
    if message.author.bot:
        return

    # Process answer attempts in target channel
    if active_question and message.channel.id == CHANNEL_ID:
        user_guess = message.content.strip().lower()

        if user_guess == active_question["answer"]:
            user_id = message.author.id
            user_scores[user_id] = user_scores.get(user_id, 0) + 10

            await message.channel.send(
                f"🎉 {message.author.mention} got it right! The answer was **{active_question['answer']}** (+10 points).\n"
                f"Total points: **{user_scores[user_id]}**"
            )
            # Reset active question once answered
            active_question = None

    # Process bot commands
    await bot.process_commands(message)


# Command to force-trigger a test question
@bot.command()
async def test(ctx):
    global active_question
    prompt, answer = generate_question()
    active_question = {"answer": str(answer).lower(), "prompt": prompt}
    await ctx.send(f"**Test Question:** (Answer: `{answer}`)\n{prompt}")


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