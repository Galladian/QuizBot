import random
import asyncio
import discord
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True  # Required to read channel messages for answers

bot = commands.Bot(command_prefix="!", intents=intents)

CHANNEL_ID = 1523280307204128868

# Track active question state and user scores
active_question = None  # Holds dict: {"answer": int, "type": str}
user_scores = {}        # Stores user_id: score

@bot.command()
async def test(ctx):
    prompt, answer = generate_arithmetic_question()
    global active_question
    active_question = {"answer": answer, "prompt": prompt}
    await ctx.send(f"🧪 **Test Question:** (Answer: `{answer}`)\n{prompt}")

def generate_arithmetic_question():
    """Generates one of four arithmetic questions and returns (prompt_string, correct_answer)."""
    op = random.choice(["multiplication", "division", "addition", "subtraction"])

    if op == "multiplication":
        a = random.randint(2, 99)
        b = random.randint(2, 99)
        return f"Solve: **{a} × {b}**", a * b

    elif op == "division":
        a = random.randint(2, 99)
        b = random.randint(2, 99)
        product = a * b
        # Displays (a * b) / b so the answer is always a
        return f"Solve: **{product} ÷ {b}**", a

    elif op == "addition":
        a = random.randint(1, 9999)
        b = random.randint(1, 9999)
        return f"Solve: **{a} + {b}**", a + b

    elif op == "subtraction":
        a = random.randint(1, 9999)
        b = random.randint(1, 9999)
        # Ensure no negative numbers
        high, low = max(a, b), min(a, b)
        return f"Solve: **{high} - {low}**", high - low


@tasks.loop(hours=1)
async def hourly_question_check():
    global active_question

    # 66% chance to trigger
    if random.random() < 0.66:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            prompt, answer = generate_arithmetic_question()
            active_question = {"answer": answer, "prompt": prompt}
            await channel.send(f"🎲 **Speed Math Challenge!** (First to answer gets 10 points)\n{prompt}")


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

    # Ignore messages sent by the bot itself
    if message.author.bot:
        return

    # Process correct answers if a question is active in the designated channel
    if active_question and message.channel.id == CHANNEL_ID:
        try:
            user_answer = int(message.content.strip())
            if user_answer == active_question["answer"]:
                user_id = message.author.id
                user_scores[user_id] = user_scores.get(user_id, 0) + 10
                
                await message.channel.send(
                    f"🎉 {message.author.mention} got it right! The answer was **{active_question['answer']}** (+10 points).\n"
                    f"Total points: **{user_scores[user_id]}**"
                )
                # Clear active question so no one else can claim points for it
                active_question = None
        except ValueError:
            # Message wasn't a valid integer, ignore it
            pass

    await bot.process_commands(message)


# Command to check current leaderboard scores
@bot.command()
async def points(ctx):
    score = user_scores.get(ctx.author.id, 0)
    await ctx.send(f"{ctx.author.mention}, you currently have **{score}** points!")


bot.run(TOKEN)