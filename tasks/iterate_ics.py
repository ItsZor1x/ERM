import discord
from discord.ext import commands, tasks

from utils import prc_api
from utils.prc_api import ServerStatus, Player
from utils.utils import interpret_content, interpret_embed


@tasks.loop(minutes=5, reconnect=True)
async def iterate_ics(bot):
    # This will aim to constantly update the Integration Command Storage
    # and the relevant storage data.
    async for item in bot.ics.db.find({}):
        try:
            guild = await bot.fetch_guild(item['guild'])
        except discord.HTTPException:
            continue

        selected = None
        custom_command_data = await bot.custom_commands.find_by_id(item['guild']) or {}
        for command in custom_command_data.get('commands', []):
            if command['id'] == item['_id']:
                selected = command

        if not selected:
            continue

        try:
            status: ServerStatus = await bot.prc_api.get_server_status(guild.id)
        except prc_api.ResponseFailure:
            status = None

        if not isinstance(status, ServerStatus):
            continue 

        try:
            queue: int = await bot.prc_api.get_server_queue(guild.id, minimal=True)
            players: list[Player] = await bot.prc_api.get_server_players(guild.id)
        except prc_api.ResponseFailure:
            continue

        mods: int = len(list(filter(lambda x: x.permission == "Server Moderator", players)))
        admins: int = len(list(filter(lambda x: x.permission == "Server Administrator", players)))
        total_staff: int = len(list(filter(lambda x: x.permission != 'Normal', players)))
        onduty: int = len([i async for i in bot.shift_management.shifts.db.find({
            "Guild": guild.id, "EndEpoch": 0
        })])

        new_data = {
            'join_code': status.join_key,
            'players': status.current_players,
            'max_players': status.max_players,
            'queue': queue,
            'staff': total_staff,
            'admins': admins,
            'mods': mods,
            "onduty": onduty
        }
        # print(json.dumps(new_data, indent=4))

        if new_data != item['data']:
            await bot.ics.db.update_one(
                {"_id": item["_id"]},
                {"$set": {"data": new_data}}
            )

            for arr in item['associated_messages']:
                channel_id, message_id = arr[0], arr[1]
                
                channel = guild.get_channel(channel_id)
                if not channel:
                    try:
                        channel = await guild.fetch_channel(channel_id)
                    except discord.HTTPException:
                        continue

                message = None
                try:
                    message = channel.get_partial_message(message_id)
                    await message.fetch()
                except (discord.NotFound, discord.HTTPException):
                    continue

                try:
                    await message.edit(
                        content=await interpret_content(bot, await bot.get_context(message), channel,
                                                     selected['message']['content'], item['_id']),
                        embeds=[
                            (await interpret_embed(bot, await bot.get_context(message), channel, embed,
                                               item['_id'])) for embed in selected['message']['embeds']
                        ] if selected['message']['embeds'] is not None else []
                    )
                except discord.HTTPException as e:
                    print(f"Failed to edit message: {e}") 

