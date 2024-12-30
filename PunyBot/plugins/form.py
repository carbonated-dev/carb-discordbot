import datetime

import yaml
from disco.api.http import APIException
from disco.bot import Plugin
from disco.types.application import InteractionType
from disco.types.message import MessageComponent, ComponentTypes, ButtonStyles, ActionRow, MessageEmbed

from PunyBot import CONFIG
from PunyBot.constants import Messages
from PunyBot.models.collaboration import CollaborationRequest


class FormPlugin(Plugin):
    def load(self, ctx):
        super(FormPlugin, self).load(ctx)

    @Plugin.command('sendcollabform')
    def send_collab_form_msg(self, event):
        # Generate the button
        components = ActionRow()

        modal_button = MessageComponent()
        modal_button.type = ComponentTypes.BUTTON
        modal_button.style = ButtonStyles.SECONDARY
        modal_button.custom_id = "start_collabform"
        modal_button.label = "Start Collaboration Form"
        modal_button.emoji = {'name': "📝"}

        components.add_component(modal_button)
        # Return the message
        return event.channel.send_message(content=Messages.collab_form_message, components=[components.to_dict()])

    @Plugin.listen("InteractionCreate", conditional=lambda e: e.type == InteractionType.MESSAGE_COMPONENT and e.data.custom_id == "start_collabform")
    def send_collab_form_modal(self, event):

        # Get modal format from interactions file
        with open("./config/interactions.yaml", "r") as raw_interaction_components:
            interaction_components = yaml.safe_load(raw_interaction_components)

        # Send the modal
        return event.reply(type=9, modal=interaction_components['components']['collab_modal'])

    @Plugin.listen("InteractionCreate", conditional=lambda e: e.type == InteractionType.MODAL_SUBMIT and e.data.custom_id == "collab_form_submit")
    def collab_form_submission(self, event):
        # Get current timestamp for tracking
        current_timestamp = datetime.datetime.now(datetime.timezone.utc)

        # Set up data for storing
        data = {
            "contact_email": None,
            "project_name": None,
            "project_description": None,
            "collab_request": None
        }

        # Get all data from submitted modal
        for field in event.interaction.data.components:
            match field.components[0].custom_id:
                case 'contact_email':
                    data["contact_email"] = field.components[0].value
                case 'project_name':
                    data["project_name"] = field.components[0].value
                case 'project_description':
                    data["project_description"] = field.components[0].value
                case 'collab_request':
                    data["collab_request"] = field.components[0].value

        # Create the submission in the database
        submission = CollaborationRequest.create(user_id=event.member.id, submission_date=current_timestamp, response=data)

        # Response formats for both Users/Backend Channel
        response_format_user = (f"# Collaboration Form Received!"
        f"\n### Submission ID: `{submission.id}`"
        f"\n### Submmitted On: <t:{int(current_timestamp.timestamp())}:F>"
        "\n### Your Response")

        response_format_backend = (f"# Submission #`{submission.id}`"
        f"\n### User: <@{event.member.id}> `{event.member.user.username} - {event.member.id}`"
        f"\n### Submmitted On: <t:{int(current_timestamp.timestamp())}:F>")

        # Create the embeds per response component and adds them to a list to determine how many messages will be sent.
        # Discord has a 6000-character limit per message for all embeds on a message. Which means if a 4000 character response
        # is sent, the embeds will have to be broken up into multiple messages.
        # To do this, get the base length of the email and project name (Which should already be under 6000 characters *Due to length constraints in the modal component*
        # As the other embed components are made, it calculates the character count and makes multiple messages as needed.
        contact_email = MessageEmbed()
        contact_email.title = "Contact Email"
        contact_email.description = f"```{data['contact_email'].replace('`', '\`')}```"

        project_name = MessageEmbed()
        project_name.title = "What is the name of your project?"
        project_name.description = f"```{data['project_name'].replace('`', '\`')}```"

        embed_lists = [[contact_email, project_name]]

        base_embed_length = len(contact_email.title) + len(contact_email.description) + len(project_name.title) + len(project_name.description)

        project_description = MessageEmbed()
        project_description.title = "Please describe your Project."
        project_description.description = f"```{data['project_description'].replace('`', '\`')}```"

        if len(project_description.title) + len(project_description.description) + base_embed_length < 6000:
            base_embed_length += len(project_description.title) + len(project_description.description)
            embed_lists[0].append(project_description)
        else:
            embed_lists.append([project_description])
            base_embed_length = len(project_description.title) + len(project_description.description)

        collab_request = MessageEmbed()
        collab_request.title = "What sort of collab do you have in mind?"
        collab_request.description = f"```{data['collab_request'].replace('`', '\`')}```"

        if (len(collab_request.title) + len(collab_request.description) + base_embed_length < 6000) and len(embed_lists) == 1:
            embed_lists[0].append(collab_request)
        elif (len(collab_request.title) + len(collab_request.description) + base_embed_length < 6000) and len(embed_lists) == 2:
            embed_lists[1].append(collab_request)
        else:
            embed_lists.append([collab_request])

        # Reply to the user saying submission modal was recieved.
        event.reply(type=4, content=Messages.collab_form_submission_success, flags=(1 << 6))

        # Send the initial submission message to the backend channel first, and then to the user.
        self.client.state.channels.get(CONFIG.collab_form_submission_channel).send_message(content=response_format_backend, embeds=embed_lists[0])

        try:
            event.member.user.open_dm().send_message(content=response_format_user, embeds=embed_lists[0])
        except APIException as e:
            pass

        # If multiple messages are needed, get rid of the ones we already sent.
        embed_lists.pop(0)

        # If multiple messages are needed, send them to the backend channel first, and then to the user.
        if len(embed_lists):
            for embed_set in embed_lists:
                self.client.state.channels.get(CONFIG.collab_form_submission_channel).send_message(embeds=embed_set)
                try:
                    event.member.user.open_dm().send_message(embeds=embed_lists[0])
                except APIException as e:
                    pass
