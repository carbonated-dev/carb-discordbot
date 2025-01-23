import datetime
from copy import copy

import gevent
import yaml
from disco.api.http import APIException
from disco.bot import Plugin
from disco.types.application import InteractionType
from disco.types.channel import MessageIterator
from disco.types.message import ActionRow, MessageComponent, ComponentTypes, ButtonStyles, SelectOption, MessageEmbed

from PunyBot.constants import Messages, CONFIG
from PunyBot.models.support import SupportTicket, TicketStatus

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S.%f%z"


class SupportPlugin(Plugin):
    def load(self, ctx):

        with open("./config/interactions.yaml", "r") as raw_interaction_components:
            interaction_components = yaml.safe_load(raw_interaction_components)

        self.modal = interaction_components['components']['support_ticket_modal']

        self.close_modal = interaction_components['components']['support_close_modal']

        super(SupportPlugin, self).load(ctx)

    def has_valid_support_roles(self, event, member=None):
        if member:
            if isinstance(member, int):
                gmember = self.client.state.guilds.get(event.guild.id).get_member(member)
                if not gmember:
                    return False
                if bool(set(gmember.roles).intersection(CONFIG.support_system.support_roles)):
                    return True
                else:
                    return False
        if bool(set(event.member.roles).intersection(CONFIG.support_system.support_roles)):
            return True
        else:
            return False

    def close_ticket(self, ticket):
        pass

    def update_ticket_message(self, ticket, event):
        message = self.client.api.channels_messages_get(CONFIG.support_system.ticket_submission_channel, ticket.ticket_extra["ticket_message"])
        components = self.generate_ticket_components(ticket, event)
        message.edit(embeds=[self.generate_ticket_embed(ticket)], components=components)

    def generate_ticket_components(self, ticket, event):
        if type(ticket) is not SupportTicket:
            ticket = SupportTicket.get(id=ticket)

        ar = ActionRow()

        channel_button = MessageComponent()
        channel_button.type = ComponentTypes.BUTTON
        if ticket.ticket_extra.get("support_channel"):
            channel_button.style = ButtonStyles.LINK
            channel_button.url = f"https://discord.com/channels/{event.guild.id}/{ticket.ticket_extra.get("support_channel")}"
            channel_button.label = "Go to support channel"
        else:
            channel_button.style = ButtonStyles.SUCCESS
            channel_button.label = "Create Temp Channel"
            channel_button.custom_id = f"ticket_create_channel_{ticket.id}"
            channel_button.emoji = {'name': '📒'}

        ar.add_component(channel_button)

        close_button = MessageComponent()
        close_button.type = ComponentTypes.BUTTON
        close_button.custom_id = f"ticket_close_{ticket.id}"
        close_button.style = ButtonStyles.DANGER
        close_button.label = "Close Ticket"
        close_button.emoji = None

        ar.add_component(close_button)

        return [ar.to_dict()]

    def generate_ticket_embed(self, ticket, for_user=False):

        if type(ticket) is not SupportTicket:
            ticket = SupportTicket.get(id=ticket)

        user = self.client.api.users_get(ticket.user_id)
        ticket_timestamp = ticket.submission_date.timestamp() if type(ticket.submission_date) is datetime.datetime else datetime.datetime.strptime(ticket.submission_date, DATETIME_FORMAT).timestamp()
        ticket_embed = MessageEmbed()

        if for_user:
            content = (f"# Ticket #`{ticket.id}`"
                       f"\n**Opened at** <t:{int(ticket_timestamp)}:f> (<t:{int(ticket_timestamp)}:R>)"
                       f"\n**Category** `{ticket.ticket_extra['category'].title()}`"
                       f"\n\n**Subject** \n```{ticket.ticket_subject.replace('`', '\`')}```"
                       f"\n**Description** \n```{ticket.ticket_description.replace('`', '\`')}```"
                       )
            ticket_embed.color = 0x44ff00
        else:
            content = (f"# Ticket #`{ticket.id}`"
                       f"\n**Opened at** <t:{int(ticket_timestamp)}:f> (<t:{int(ticket_timestamp)}:R>)"
                       f"\n**User** <@{user.id}> `{user.username} - {user.id}`"
                       f"\n**Category** `{ticket.ticket_extra['category'].title()}`"
                       f"{f"\n**Ticket Channel**: <#{ticket.ticket_extra.get('support_channel')}>" if ticket.ticket_extra.get('support_channel') else ""}"
                       f"\n\n**Subject** \n```{ticket.ticket_subject.replace('`', '\`')}```"
                       f"\n**Description** \n```{ticket.ticket_description.replace('`', '\`')}```"
                       )
            ticket_embed.color = 0x44ff00

        ticket_embed.description = content
        return ticket_embed

    @Plugin.command('sendsupportmessage')
    def send_collab_form_msg(self, event):
        # Generate the button
        components = ActionRow()

        modal_button = MessageComponent()
        modal_button.type = ComponentTypes.BUTTON
        modal_button.style = ButtonStyles.SECONDARY
        modal_button.custom_id = "start_support"
        modal_button.label = "Start Support Ticket"
        modal_button.emoji = {'name': "📝"}

        components.add_component(modal_button)
        # Return the message
        return event.channel.send_message(content=Messages.support_form_message, components=[components.to_dict()])

    @Plugin.listen("InteractionCreate", conditional=lambda e: e.type == InteractionType.MESSAGE_COMPONENT and e.data.custom_id == "start_support")
    def start_support(self, event):
        components = ActionRow()

        category_select = MessageComponent()
        category_select.placeholder = "Select Support Category"
        category_select.max_values = 1
        category_select.min_values = 1
        category_select.type = ComponentTypes.STRING_SELECT
        category_select.custom_id = "support_category_select"

        for category_key, category_label in CONFIG.support_system.support_categories.items():
            option = SelectOption()
            option.label = category_label
            option.value = category_key
            option.emoji = None

            category_select.options.append(option)

        components.add_component(category_select)

        message = "Please select the category for this support request."

        event_message = event.reply(type=4, content=message, components=[components.to_dict()], flags=(1 << 6))

        try:
            subject_select = self.wait_for_event("InteractionCreate", conditional=lambda
                e: e.type == InteractionType.MESSAGE_COMPONENT and e.message.id == event_message.message.id).get(
                timeout=60)
        except gevent.Timeout as e:
            event_message.edit("Timed Out, please try again...").after(5)
            return event.delete()

        category = subject_select.data.values[0]

        modal = copy(self.modal)

        modal["custom_id"] = f"support_form_submit_{category}"

        # Send the modal
        subject_select.reply(type=9, modal=modal)
        return event.delete()

    @Plugin.listen("InteractionCreate", conditional=lambda e: e.type == InteractionType.MODAL_SUBMIT and e.data.custom_id.startswith("support_form_submit_"))
    def support_form_submit(self, event):
        current_timestamp = datetime.datetime.now(datetime.timezone.utc)
        data = {
            "subject": None,
            "description": None,
        }
        extra_data = {
            "category": event.data.custom_id.replace("support_form_submit_", ""),
        }

        for field in event.interaction.data.components:
            match field.components[0].custom_id:
                case 'support_subject':
                    data["subject"] = field.components[0].value
                case 'support_description':
                    data["description"] = field.components[0].value

        ticket = SupportTicket.create(user_id=event.member.id, submission_date=current_timestamp, ticket_subject=data["subject"], ticket_description=data["description"], ticket_extra=extra_data)
        ticket_embed = self.generate_ticket_embed(ticket)
        components = self.generate_ticket_components(ticket, event)

        ticket_message = self.client.state.channels.get(CONFIG.support_system.ticket_submission_channel).send_message(embeds=[ticket_embed], components=components)

        ticket.ticket_extra["ticket_message"] = ticket_message.id
        ticket.save()

        could_dm = True

        try:
            event.member.user.open_dm().send_message("### Ticket Received!", embeds=[self.generate_ticket_embed(ticket, for_user=True)])
        except APIException as e:
            could_dm = False

        if could_dm:
            return event.reply(type=4, content=Messages.support_form_submission_success, flags=(1 << 6))
        else:
            return event.reply(type=4, content=Messages.support_form_submission_no_dm, embeds=[self.generate_ticket_embed(ticket, for_user=True)], flags=(1 << 6))


    @Plugin.listen("InteractionCreate", conditional=lambda e: e.type == InteractionType.MESSAGE_COMPONENT and e.data.custom_id.startswith("ticket_"))
    def manage_ticket(self, event):
        ticket_id = None
        ticket_function = None

        if not event.data.custom_id.split("_")[-1].isnumeric():
            return
        else:
            ticket_id = int(event.data.custom_id.split("_")[-1])

        ticket_function = event.data.custom_id.replace("ticket_", "")
        ticket_function = ticket_function.replace(f"_{ticket_id}", "")

        ticket = SupportTicket.get_or_none(id=ticket_id)

        if not ticket:
            return event.reply(type=4, content="**ERROR** `Ticket not found!`", flags=(1 << 6))

        match ticket_function:
            case "create_channel":
                user = self.client.api.users_get(ticket.user_id)
                support_channel = event.guild.create_text_channel(name=f"{ticket.id}-{ticket.ticket_extra.get("category", "other")}-{user.username}",
                                                                  parent_id=CONFIG.support_system.ticket_channel_category,
                                                                  reason=f"{event.member} created a support channel for Ticket {ticket.id}")
                self.client.api.channels_permissions_modify(support_channel.id, user.id, 52224, 0, 1)
                support_channel.send_message(embeds=[self.generate_ticket_embed(ticket)])
                ticket.ticket_extra["support_channel"] = support_channel.id
                ticket.save()
                self.update_ticket_message(ticket, event)
                try:
                    user.open_dm().send_message(Messages.support_new_temp_channel_user.format(ticket=ticket, channel_id=support_channel.id))
                except APIException as e:
                    support_channel.send_message(Messages.support_new_temp_channel_no_dm.format(ticket=ticket), allowed_mentions={'parse': ["users"]})
                return event.reply(type=6)
            case "close":

                close_ar = ActionRow()

                close_reason_select = MessageComponent()
                close_reason_select.placeholder = "Select Close Reason"
                close_reason_select.max_values = 1
                close_reason_select.min_values = 1
                close_reason_select.type = ComponentTypes.STRING_SELECT
                close_reason_select.custom_id = "close_reason_select"

                for i in range(0, len(CONFIG.support_system.support_close_reasons)):
                    option = SelectOption()
                    option.label = CONFIG.support_system.support_close_reasons[i]
                    option.value = i
                    option.emoji = None

                    close_reason_select.options.append(option)

                other = SelectOption()
                other.label = "Other"
                other.value = "other"
                other.emoji = None

                close_reason_select.options.append(other)

                close_ar.add_component(close_reason_select)

                message = "Please select the reason for closing this request."

                event_message = event.reply(type=4, content=message, components=[close_ar.to_dict()], flags=(1 << 6))

                try:
                    close_reason = self.wait_for_event("InteractionCreate", conditional=lambda
                        e: e.type == InteractionType.MESSAGE_COMPONENT and e.message.id == event_message.message.id).get(
                        timeout=60)
                except gevent.Timeout as e:
                    event_message.edit("Timed Out, please try again...").after(5)
                    return event.delete()

                reason = ""

                if close_reason.data.values[0] == "other":
                    modal = copy(self.close_modal)

                    modal["custom_id"] = f"support_close_reason_{ticket.id}"
                    close_reason.reply(type=9, modal=modal)
                    event.delete()
                    try:
                        close_reason = self.wait_for_event("InteractionCreate", conditional=lambda
                            e: e.type == InteractionType.MODAL_SUBMIT and e.data.custom_id == f"support_close_reason_{ticket.id}").get(
                            timeout=60)
                    except gevent.Timeout as e:
                        return

                    reason = close_reason.interaction.data.components[0].components[0].value
                    close_reason.reply(type=4, content="👍", flags=(1 << 6))
                    close_reason.after(3).delete()

                else:
                    event.delete()
                    reason = CONFIG.support_system.support_close_reasons[int(close_reason.data.values[0])]


                user = self.client.api.users_get(ticket.user_id)
                ticket.status = TicketStatus.CLOSED
                attachments = None
                if ticket.ticket_extra.get("support_channel"):
                    raw_ticket_messages = {}
                    messages = self.client.api.channels_get(ticket.ticket_extra["support_channel"]).messages_iter(direction=MessageIterator.Direction.UP, bulk=True)
                    for mchunk in messages:
                        for message in mchunk:
                            if not message.content and message.author.id == self.client.state.me.id:
                                raw_ticket_messages[message.id] = f"| Ticket ID - {ticket.id} | Ticket Category - {ticket.ticket_extra['category'].title()} | Ticket Open Date {ticket.submission_date} |\nTicket Subject: {ticket.ticket_subject}\nTicket Description: {ticket.ticket_description}\n\n"
                                continue
                            raw_ticket_messages[message.id] = f"[{message.timestamp.strftime("%B %d, %Y %H:%M:%S")}] {message.author.username}{'🔨' if self.has_valid_support_roles(event, member=message.author.id) else ''} ({message.author.id}) » {message.content}"
                    try:
                        self.client.api.channels_delete(ticket.ticket_extra["support_channel"],
                                                        reason=f"Ticket {ticket.id} closed by {event.member.user.username}.")
                    except APIException as e:
                        self.log.error(
                            f"[Ticket Closure] Unable to delete ticket channel for Ticket ID: {ticket.id}: {e.response}")
                    if len(raw_ticket_messages):
                        raw_messages = "\n".join(list(dict(sorted(raw_ticket_messages.items())).values()))
                        attachments = [(f"ticket-{ticket.id}-transcript.txt", str.encode(raw_messages))]

                if not attachments:
                    attachments = [(f"ticket-{ticket.id}-transcript.txt", str.encode(f"| Ticket ID - {ticket.id} | Ticket Category - {ticket.ticket_extra['category'].title()} | Ticket Open Date {ticket.submission_date} |\nTicket Subject: {ticket.ticket_subject}\nTicket Description: {ticket.ticket_description}"))]

                try:
                    self.client.api.channels_messages_delete(CONFIG.support_system.ticket_submission_channel, ticket.ticket_extra["ticket_message"])
                except APIException as e:
                    self.log.error(f"[Ticket Closure] Unable to delete ticket message for Ticket ID: {ticket.id}: {e.response}")
                self.client.api.channels_messages_create(CONFIG.support_system.ticket_logs_channel, content=f"[<t:{int(datetime.datetime.now().timestamp())}:f>] [`Category: {ticket.ticket_extra['category'].title()}`] **Ticket #**`{ticket.id}` Closed by `{event.member.user.username}`\n**User**: <@{user.id}> (`{user.username} - {user.id}`) \n**Reason**\n```{reason}```",
                                                         attachments=attachments)
                ticket.save()
                try:
                    user.open_dm().send_message(Messages.support_ticket_close_user.format(ticket=ticket, close_reason=reason), attachments=attachments)
                except APIException as e:
                    pass
                return
            case _:
                return
