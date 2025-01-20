import contextlib
import os
import random
from datetime import datetime

import gevent
import requests
import yaml
from disco.api.http import APIException
from disco.bot import Plugin
from disco.bot.command import CommandEvent
from disco.types.application import InteractionType, ApplicationCommandTypes
from disco.types.channel import ChannelType
from disco.types.message import ActionRow, MessageComponent, ComponentTypes, SelectOption, ButtonStyles, MessageEmbed, \
    TextInputStyles, MessageModal
from disco.types.permissions import Permissions
from disco.types.user import Status, Activity, ActivityTypes
from dotenv import load_dotenv

from PunyBot import CONFIG
from PunyBot.constants import Messages


class CorePlugin(Plugin):
    def load(self, ctx):
        load_dotenv()

        self.guild_menu_roles = {}

        self.current_status_app = None
        self.bad_requests = 0
        self.schedule_restarts = 0

        # Player/Name Cache
        self.game_titles = {}
        self.player_counts = {}

        for gid in CONFIG.roles:
            self.guild_menu_roles[gid] = []
            for role in CONFIG.roles[gid].select_menu:
                self.guild_menu_roles[gid].append(role.role_id)

        super(CorePlugin, self).load(ctx)

    # Method to handle any bad steam requests from status updates
    def handle_bad_requests(self):
        self.bad_requests += 1
        if self.bad_requests > 10:
            self.schedule_restarts += 1
            if self.schedule_restarts > 3:
                # Reset values back to 0.
                self.bad_requests = 0
                self.schedule_restarts = 0

                # Log and kill the scheduled task
                self.log.error("Error: More than 3 restarts on the Status Scheduler. Killing until reboot or forced to restart via command.")
                self.schedules['update_status'].kill()
                return

            # Log, grab tasks, sleep, re-register, kill old one, reset counter.
            self.log.error("Error: More than 10 bad steam reponses. Killing status scheduler, pausing for 15 seconds, and retrying.")
            schedule = self.schedules['update_status']
            gevent.sleep(10)
            self.register_schedule(self.update_status, 5, init=False)
            self.bad_requests = 0
            schedule.kill()
        return

    def update_status(self):
        steam_key = os.getenv("STEAM_API_KEY")
        players = 0
        if not self.player_counts.get(self.current_status_app) or (datetime.now().timestamp() - self.player_counts[self.current_status_app]['last_requested']) > 30:
            try:
                r = requests.get(
                    f"https://partner.steam-api.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/?key={steam_key}&appid={self.current_status_app}")
                if r.status_code == 403:
                    self.log.error(f"Error: 403 Forbidden Given when trying to get player count for APP ID: {self.current_status_app}. Are you using a valid API Key?")
                elif not r.json():
                    self.log.error("Error: Unable to grab player information")
                elif r.json()['response'].get('player_count'):
                    players = r.json()['response']['player_count']
                    self.player_counts[self.current_status_app] = {'count': players, 'last_requested': datetime.now().timestamp()}
            except Exception as e:
                self.log.error("Error: Exception when getting players from Steam's API. Possible bad response? Skipping Status Update...")
                self.handle_bad_requests()
                return
        else:
            players = self.player_counts[self.current_status_app]['count']

        app_name = None
        if self.game_titles.get(self.current_status_app):
            app_name = self.game_titles.get(self.current_status_app)
        else:
            try:
                r = requests.get(f"https://store.steampowered.com/api/appdetails?appids={self.current_status_app}")
                if not r.json():
                    self.log.error("Error: Unable to grab store app page")
                else:
                    if not r.json()[str(self.current_status_app)]['success']:
                        self.log.error("Error: App not found on the steam store")
                    else:
                        app_name = r.json()[str(self.current_status_app)]['data']['name']
                        self.game_titles[self.current_status_app] = app_name
            except Exception as e:
                self.log.error("Error: Exception when getting app information from Steam's API. Possible bad response? Skipping Status Update...")
                self.handle_bad_requests()
                return

        self.bot.client.update_presence(Status.ONLINE,
                                        Activity(name=f"{players} {app_name} player{'s' if players != 1 else ''}", type=ActivityTypes.WATCHING))

        if CONFIG.status_apps.index(self.current_status_app) == (len(CONFIG.status_apps) - 1):
            self.current_status_app = CONFIG.status_apps[0]
        else:
            self.current_status_app = CONFIG.status_apps[CONFIG.status_apps.index(self.current_status_app) + 1]

    @contextlib.contextmanager
    def send_control_message(self):
        embed = MessageEmbed()
        embed.set_footer(text='PunyBot Log')
        embed.timestamp = datetime.utcnow().isoformat()
        embed.color = 0x779ecb
        try:
            yield embed
            self.bot.client.api.channels_messages_create(CONFIG.logging_channel, embeds=[embed])
        except APIException:
            return self.log.exception('Failed to send control message:')

    @Plugin.listen('Ready')
    def on_ready(self, event):
        # Bot Startup Logging.
        self.log.info(f"Bot connected as {self.client.state.me}")
        gw_info = self.bot.client.api.gateway_bot_get()

        with self.send_control_message() as embed:
            if self.bot.client.gw.reconnects:
                embed.title = 'Reconnected'
                embed.color = 0xffb347
            else:
                embed.title = 'Connected'
                embed.color = 0x77dd77
                self.log.info(f'Started session {event.session_id}')

            embed.add_field(name='Session ID', value=f'`{event.session_id}`', inline=True)
            embed.add_field(name='Session Starts Remaining',
                            value='`{}/{}`'.format(gw_info['session_start_limit']['remaining'],
                                                   gw_info['session_start_limit']['total']), inline=True)
            if self.bot.client.gw.last_conn_state:
                embed.add_field(name='Last Connection Close', value=f'`{self.bot.client.gw.last_conn_state}`',
                                inline=True)

        # Steam Game Player Count Status.
        if len(CONFIG.status_apps):
            steam_key = os.getenv("STEAM_API_KEY")
            if not steam_key:
                 self.log.error("Error: No valid steam api key found. Please add the following environment variable 'STEAM_API_KEY' to your docker config/.env with the value being a publisher API key.")
            else:
                r = requests.get(f"https://partner.steam-api.com/ISteamApps/GetPartnerAppListForWebAPIKey/v1?key={steam_key}")
                if r.status_code == 403:
                    self.log.error("Error: Invalid Publisher Steam API Key. Can't get player counts!")
                else:
                    from random import choice
                    self.current_status_app = choice(CONFIG.status_apps)
                    self.register_schedule(self.update_status, 5)
        else:
            self.log.info("Status apps is empty, skipping setting bot status.")

        # Register all commands globally.
        with open("./config/interactions.yaml", "r") as raw_interaction_components:
            interaction_components = yaml.safe_load(raw_interaction_components)

        to_register = []
        for global_type, global_type_commands in interaction_components['commands']['global'].items():
            if len(global_type_commands):
                self.log.info(f"Found {len(global_type_commands)} {global_type} command(s) to register...")
                for command in global_type_commands:
                    command["type"] = getattr(ApplicationCommandTypes, global_type.upper())
                    to_register.append(command)

        self.log.info(f"Attempting to register {len(to_register)} commands...")

        updated_commands = self.client.api.applications_global_commands_bulk_overwrite(to_register)
        self.log.info(f"Successfully Registered {len(updated_commands)} commands!")


    # @Plugin.listen('Resumed')
    # def on_resumed(self, event):
    #     with self.send_control_message() as embed:
    #         embed.title = 'Resumed'
    #         embed.color = 0xffb347
    #         embed.add_field(name='Replayed Events', value=str(self.bot.client.gw.replayed_events))

    @Plugin.listen('MessageCreate')
    def on_command_msg(self, event):
        """
        Borrow by Nadie <iam@nadie.dev> (https://github.com/hackerjef/) [Used with permission]
        """
        if event.message.author.bot:
            return
        if not event.guild:
            return

        has_permission = False
        for role_id in CONFIG.admin_role:
            if role_id in event.member.roles:
                has_permission = True
                break

        if not has_permission:
            return

        commands = self.bot.get_commands_for_message(False, {}, '!', event.message)
        if not commands:
            return
        for command, match in commands:
            return command.plugin.execute(CommandEvent(command, event, match))

    # TODO: Replace with /command (Send message template. Which would include a interaction selection for what ones are active)
    @Plugin.command('sendmenumsg')
    def test_menu(self, event):

        components = ActionRow()

        select_menu = MessageComponent()
        select_menu.type = ComponentTypes.STRING_SELECT
        select_menu.custom_id = f"roles_menu_{event.guild.id}"
        select_menu.placeholder = "Which roles would you like?"

        for role in CONFIG.roles[event.guild.id].select_menu:
            option = SelectOption()
            option.label = role.display_name
            option.value = role.role_id
            option.emoji = None

            select_menu.options.append(option)

        select_menu.max_values = len(CONFIG.roles[event.guild.id].select_menu)
        select_menu.min_values = 0

        components.add_component(select_menu)

        return event.channel.send_message(content="",
                                          components=[components.to_dict()])

    # TODO: Replace with /command (Send message template. Which would include a interaction selection for what ones are active)
    @Plugin.command('sendrulesmsg')
    def send_rules_message(self, event):
        content = Messages.rules_message
        return event.channel.send_message(content=content)

    # TODO: Replace with /command (Send message template. Which would include a interaction selection for what ones are active)
    @Plugin.command('sendrulesbuttonmsg')
    def send_rules_button_message(self, event):
        components = ActionRow()

        # TODO: Replace with component template
        button = MessageComponent()
        button.type = ComponentTypes.BUTTON
        button.style = ButtonStyles.SUCCESS
        button.custom_id = f"rules_{event.guild.id}"
        button.label = "I Agree"
        button.emoji.name = "✅"

        components.add_component(button)

        return event.channel.send_message(content=Messages.rules_message,
                                          components=[components.to_dict()])

    # TODO: Replace with /command
    @Plugin.command('forcestatus')
    def force_status(self, event):
        if self.schedules.get('update_status'):
            self.log.info("'forcestatus' command ran and active schedule found... killing schedule...")
            self.schedules['update_status'].kill()

        self.log.info("'forcestatus' command ran. Restarting schedule...")
        self.register_schedule(self.update_status, 5)
        return event.msg.add_reaction("👍")

    @Plugin.command('echo', '<msg:snowflake> [channel:snowflake|channel] [topic:str...]')
    def echo_command(self, event, msg, channel=None, topic=None):
        api_message = None
        channel_to_send_to = None

        if not channel:
            channel_to_send_to = event.channel
        else:
            if self.client.state.channels.get(channel):
                channel_to_send_to = self.client.state.channels.get(channel)
            elif self.client.state.threads.get(channel):
                channel_to_send_to = self.client.state.threads.get(channel)
            else:
                event.msg.reply("`Error`: **Unknown Channel...**")
                return event.msg.add_reaction("👎")

        try:
            api_message = self.client.api.channels_messages_get(event.channel.id, msg)
        except APIException as e:
            if e.code == 10008:
                return event.msg.reply(
                    "`Error`: **Message not found...Please make sure you are running this command in the "
                    "same channel as your original message!**")
            else:
                raise e

        if not api_message:
            event.msg.add_reaction("👎")
            return event.msg.reply("`Error`: **UNKNOWN ERROR...**")

        content = api_message.content
        attachments = []

        if api_message.attachments:
            for attachment in api_message.attachments:
                tmp = api_message.attachments[attachment]
                r = requests.get(tmp.url)
                r.raise_for_status()
                attachments.append((tmp.filename, r.content))

        # TODO: Split into multiple messages
        if len(content) > 2000:
            event.msg.add_reaction("👎")
            return event.msg.reply(f"`Error`: **Your original message is over 2000 characters** (`{len(content) - 2000} Over, {len(content)} Total`)")

        try:
            if channel_to_send_to.type == 15:
                if not topic:
                    event.msg.reply("`Error:` **Topic not set, please use** `!echo <msgID> <ChannelID> <Thread_Topic>`")
                    return event.msg.add_reaction("👎")
                msg = {'content': content, 'attachments': attachments}
                channel_to_send_to.start_forum_thread(content=content, name=topic, attachments=attachments,allowed_mentions={'parse': ["roles", "users", "everyone"]})
            else:
                channel_to_send_to.send_message(content or None, attachments=attachments,allowed_mentions={'parse': ["roles", "users", "everyone"]})
        except APIException as e:
            if e.code in [50013, 50001]:
                event.msg.add_reaction("👎")
                return event.msg.reply("`Error`: **Missing permission to echo, please check channel perms!**")
            else:
                event.msg.add_reaction("👎")
                raise e
        return event.msg.add_reaction("👍")

    @Plugin.listen('InteractionCreate')
    def test_menu_select(self, event):

        # TODO: Fix after Disco fixes their enum bug.
        if event.raw_data['interaction']['type'] != 3:
            return

        if event.data.custom_id.startswith('roles_menu_'):
            tmp_roles = event.member.roles
            for role_id in self.guild_menu_roles[event.guild.id]:
                if role_id in event.data.values:
                    continue
                if role_id in tmp_roles:
                    tmp_roles.remove(role_id)
            for selection in event.data.values:
                if selection not in tmp_roles:
                    tmp_roles.append(selection)

            event.guild.get_member(event.member.id).modify(roles=tmp_roles, reason="Updating selected roles from menu")
            # event.m.modify(roles=tmp_roles, reason="Updating selected roles from menu")

            return event.reply(type=6)

        if event.data.custom_id.startswith('rules_'):
            if CONFIG.roles[event.guild.id].rules_accepted not in event.member.roles:
                # event.m.add_role(self.guild_rules_roles.get(event.guild.id), reason="Accepted Rules")
                event.guild.get_member(event.member.id).add_role(CONFIG.roles[event.guild.id].rules_accepted,
                                                            reason="Accepted Rules")

            return event.reply(type=6)


    @Plugin.listen("InteractionCreate", conditional=lambda e: e.type == InteractionType.APPLICATION_COMMAND and e.data.name == "echo")
    def new_echo_command(self, event):
        # Grab all the data required from the command.
        message_id = None
        channel_id = None
        preview = False
        thread_name = None
        preview_msg = None

        if len(event.data.options) == 2:
            message_id = event.data.options[0].value
            channel_id = event.data.options[1].value
        else:
            for option in event.data.options:
                match option.name:
                    case "message":
                        message_id = option.value
                    case "channel":
                        channel_id = option.value
                    case "preview":
                        preview = option.value
                    case "thread_name":
                        thread_name = option.value
                    case _:
                        break

        # If for whatever reason, we are missing either a message or a channel, simply break.
        if not (message_id or channel_id):
            return event.reply(type=4, content="**Error**: `You are missing a message or channel, please try again.`", flags=(1 << 6))

        # Get the channel, and ensure it's not a forum.
        try:
            channel = self.client.api.channels_get(channel_id)
        except APIException as e:
            return event.reply(type=4, content="**Error**: `Unable to access channel.`", flags=(1 << 6))

        if channel.type in [ChannelType.GUILD_FORUM, ChannelType.GUILD_MEDIA] and not thread_name:
            return event.reply(type=4, content="**Error**: `Attempting to Echo into a forum type channel, thread name required!`",
                               flags=(1 << 6))

        # Ensure the bot has permissions to actually send the message.
        bot_permissions = channel.get_permissions(self.client.state.me.id)

        can_send_messages_and_files = (bot_permissions.can(Permissions.SEND_MESSAGES) and bot_permissions.can(Permissions.ATTACH_FILES))

        if not can_send_messages_and_files:
            return event.reply(type=4, content="**Error**: `Bot does not have message/attachment permissions in the designated channel.`", flags=(1 << 6))

        # Get the message object, needed for both preview and the final send.
        try:
            message_object = event.channel.get_message(message_id)
        except APIException as e:
            return event.reply(type=4, content="**Error**: `Message not found.`", flags=(1 << 6))

        content = message_object.content
        attachments = []

        if message_object.attachments:
            for attachment in message_object.attachments:
                tmp = message_object.attachments[attachment]
                r = requests.get(tmp.url)
                r.raise_for_status()
                attachments.append((tmp.filename, r.content))

        # TODO: Split into multiple messages, maybe?
        if len(content) > 2000:
            return event.reply(type=4, content=f"**Error**: `Original message is over 2000 characters. [{len(content) - 2000} Over, {len(content)} Total]`", flags=(1 << 6))

        # Preview if needed.
        if preview:
            buttons = ActionRow()
            confirm_button = MessageComponent()
            confirm_button.type = ComponentTypes.BUTTON
            confirm_button.style = ButtonStyles.SUCCESS
            confirm_button.label = "Click to send message."
            confirm_button.custom_id = "echo_confirm"
            confirm_button.emoji = None
            buttons.add_component(confirm_button)

            header = "```~~~ Echo Preview ~~~```"

            content_to_send = f"{header}{content}"

            # TODO: Fix broken attachments
            preview_msg = event.reply(type=4, content=content_to_send, attachments=attachments, components=[buttons.to_dict()], flags=(1 << 6))

            try:
                preview_event = self.wait_for_event("InteractionCreate", conditional=lambda e: e.type == InteractionType.MESSAGE_COMPONENT and e.message.id == preview_msg.id).get(timeout=10)
            except gevent.Timeout as e:
                header = "```~~~ Echo Timeout Passed. Echo Canceled. ~~~```"
                content_to_send = f"{header}{content}"
                confirm_button.disabled = True
                return preview_msg.edit(content=content_to_send, components=[buttons.to_dict()])

        # Send the message!
        if channel.type in [ChannelType.GUILD_FORUM, ChannelType.GUILD_MEDIA]:
            sent = channel.start_forum_thread(content=content or None, name=thread_name, attachments=attachments, allowed_mentions={'parse': ["roles", "users", "everyone"]})
        else:
            sent = channel.send_message(content=content or None, attachments=attachments, allowed_mentions={'parse': ["roles", "users", "everyone"]})

        msg_link = f"https://discord.com/channels/{event.guild.id}/{channel.id}/{sent.id}"

        if preview_msg:
            return preview_msg.edit(content=f"Echo Successful! 👍\n**{msg_link}**")
        else:
            return event.reply(type=4, content=f"Echo Successful! 👍:\n{msg_link}", flags=(1 << 6))


    @Plugin.listen("InteractionCreate", conditional=lambda e: e.type == InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE and e.data.name == "echo")
    def new_echo_command_autocomplete(self, event):
        messages = self.client.api.channels_messages_list(event.channel.id, limit=25)

        choices = []
        for msg in messages:
            if len(choices) == 25:
                break
            author_name = msg.author.username
            if not msg.content:
                if msg.attachments:
                    names = [msg.attachments[file].filename for file in msg.attachments]
                    name_str = ", ".join(names)
                    if len(name_str) > 100:
                        choices.append({
                            "name": f"{author_name}: {name_str[:95-len(author_name)]}...",
                            "value": str(msg.id)
                        })
                    else:
                        choices.append({
                            "name": f"{author_name}: {name_str}",
                            "value": str(msg.id)
                        })
                else:
                    choices.append({
                        "name": f"{author_name}: *NO CONTENT*",
                        "value": str(msg.id)
                    })
            elif len(f"{author_name}: {msg.content}") > 100:
                choices.append({
                    "name": f"{author_name}: {msg.content[:95-len(author_name)]}...",
                    "value": str(msg.id)
                })
            else:
                choices.append({
                    "name": f"{author_name}: {msg.content}",
                    "value": str(msg.id)
                })

        return event.reply(type=8, choices=choices)

    @Plugin.listen("InteractionCreate", conditional=lambda e: e.type == InteractionType.APPLICATION_COMMAND and e.data.name == "Echo Message")
    def new_echo_menu_command(self, event):
        # select = MessageComponent(type=ComponentTypes.CHANNEL_SELECT.real, min_values=1, max_values=1, channel_types=[0, 5, 11, 10, 12, 13, 15, 16])
        select = MessageComponent()
        select.type = ComponentTypes.CHANNEL_SELECT
        select.min_values=1
        select.max_values=1
        select.channel_types = [0, 5, 11, 10, 12, 13, 15, 16]
        select.custom_id = "echo_channel_select"

        confirm_button = MessageComponent()
        confirm_button.type = ComponentTypes.BUTTON
        confirm_button.style = ButtonStyles.SUCCESS
        confirm_button.label = "Confirm"
        confirm_button.custom_id = "echo_confirm"
        confirm_button.emoji = None

        ar = ActionRow()
        ar.add_component(select)
        ar2 = ActionRow()
        ar2.add_component(confirm_button)

        current_selection = None
        current_message = "Now please select a location to send this message to."
        base_response = f"**Base Message Selected**: https://discord.com/channels/{event.guild.id}/{event.channel.id}/{event.data.target_id}\n\n{current_message}"

        initial_message = event.reply(type=4, content=base_response, components=[ar.to_dict()], flags=(1 << 6))

        next_event = None

        while True:
            try:
                next_event = self.wait_for_event("InteractionCreate", conditional=lambda
                    e: e.type == InteractionType.MESSAGE_COMPONENT and e.message.id == initial_message.message.id).get(timeout=30)

                match next_event.data.custom_id:
                    case "echo_confirm":
                        break
                    case "echo_channel_select":
                        current_selection = next_event.interaction.data.values[0]
                    case _:
                        # We shouldn't get to this point, but covering all bases.
                        return

                current_message = f"Channel Selected: <#{current_selection}>"
                base_response = f"**Base Message Selected**: https://discord.com/channels/{event.guild.id}/{event.channel.id}/{event.data.target_id}\n\n{current_message}"
                initial_message.edit(content=f"{base_response}", components=[ar.to_dict(), ar2.to_dict()])
                next_event.reply(type=6)
            except gevent.Timeout as e:
                header = "```~~~ Echo Timed out ~~~```"
                content_to_send = f"{header}{base_response}"
                confirm_button.disabled = True
                # deny_button.disabled = True
                select.disabled = True
                return initial_message.edit(content=content_to_send, components=[ar.to_dict(), ar2.to_dict()])

        try:
            channel = self.client.api.channels_get(current_selection)
        except APIException as e:
            return initial_message.edit(content="**Error**: `Unable to access channel.`")

        thread_name = None
        if channel.type in [ChannelType.GUILD_FORUM, ChannelType.GUILD_MEDIA] and not thread_name:
            thread = MessageComponent()
            thread.type = ComponentTypes.TEXT_INPUT
            thread.style = TextInputStyles.SHORT
            thread.label = "Forum Channel, Thread Name Needed"
            thread.placeholder = "Really cool thread title!"
            thread.required = True
            thread.custom_id = "thread_name"

            ar1 = ActionRow()
            ar1.add_component(thread)

            modal = MessageModal()
            modal.title = "Need a thread name."
            modal.custom_id = "echo_thread_name"
            modal.add_component(ar1)

            next_event.reply(type=9, modal=modal)

            try:
                next_event = self.wait_for_event("InteractionCreate", conditional=lambda
                    e: e.type == InteractionType.MODAL_SUBMIT and e.member.id == event.member.id).get(timeout=30)
                thread_name = next_event.data.components[0].components[0].value
                next_event.reply(type=6)
            except gevent.Timeout as e:
                header = "```~~~ Echo Timed out ~~~```"
                content_to_send = f"{header}{base_response}"
                confirm_button.disabled = True
                select.disabled = True
                return initial_message.edit(content=content_to_send, components=[ar.to_dict(), ar2.to_dict()])

        bot_permissions = channel.get_permissions(self.client.state.me.id)

        can_send_messages_and_files = (
                bot_permissions.can(Permissions.SEND_MESSAGES) and bot_permissions.can(Permissions.ATTACH_FILES))

        if not can_send_messages_and_files:
            return initial_message.edit(content="**Error**: `Bot does not have message/attachment permissions in the designated channel.`")

        # Get the message object, needed for both preview and the final send.
        try:
            message_object = event.channel.get_message(event.data.target_id)
        except APIException as e:
            return initial_message.edit(content="**Error**: `Message not found.`")

        content = message_object.content
        attachments = []

        if message_object.attachments:
            for attachment in message_object.attachments:
                tmp = message_object.attachments[attachment]
                r = requests.get(tmp.url)
                r.raise_for_status()
                attachments.append((tmp.filename, r.content))

        # TODO: Split into multiple messages, maybe?
        if len(content) > 2000:
            return initial_message.edit(content=f"**Error**: `Original message is over 2000 characters. [{len(content) - 2000} Over, {len(content)} Total]`")

        # Send the message!
        if channel.type in [ChannelType.GUILD_FORUM, ChannelType.GUILD_MEDIA]:
            sent = channel.start_forum_thread(content=content or None, name=thread_name, attachments=attachments,
                                              allowed_mentions={'parse': ["roles", "users", "everyone"]})
        else:
            sent = channel.send_message(content=content or None, attachments=attachments,
                                        allowed_mentions={'parse': ["roles", "users", "everyone"]})

        msg_link = f"https://discord.com/channels/{event.guild.id}/{channel.id}/{sent.id}"

        return initial_message.edit(content=f"Echo Successful! 👍:\n{msg_link}")


    @Plugin.listen("MessageCreate", conditional=lambda e: e.channel.id in CONFIG.auto_delete_channels and CONFIG.agreement.post_process_role not in e.member.roles)
    def auto_delete_messages(self, event):
        if event.message.author.id == self.client.state.me.id:
            return
        # Attempt to avoid rate limits on channel deletions.
        delay = random.uniform(0, 1.5)
        gevent.sleep(delay)
        try:
            event.message.delete()
        except Exception:
            pass
