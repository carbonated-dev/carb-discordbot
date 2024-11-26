from disco.bot import Plugin
from disco.types.application import InteractionType
from disco.types.message import MessageModal, ActionRow, TextInputStyles, ComponentTypes, MessageComponent, ButtonStyles

from PunyBot import CONFIG
from PunyBot.constants import Messages
from PunyBot.models import Agreement


class AgreementPlugin(Plugin):
    def load(self, ctx):
        super(AgreementPlugin, self).load(ctx)

    @Plugin.listen('InteractionCreate')
    def button_listener(self, event):

        #Todo: Switch back to event.type after lib patch.
        if not (event.raw_data['interaction']['type'] != 3 or event.raw_data['interaction']['type'] != 5):
            return

        if event.raw_data['interaction']['type'] != InteractionType.MODAL_SUBMIT:
            if event.data.custom_id != "agreement_start":
                return

            if CONFIG.agreement.post_process_role in event.member.roles:
                return event.reply(type=6)

            username = MessageComponent()
            username.type = ComponentTypes.TEXT_INPUT
            username.style = TextInputStyles.SHORT
            username.label = "Do you swear by the Creed? Sign Thy Name."
            username.placeholder = event.member.user.username
            username.required = True
            username.custom_id = "username"

            ar1 = ActionRow()
            ar1.add_component(username)

            modal = MessageModal()
            modal.title = "Survivor's Creed"
            modal.custom_id = "agreement_submit"
            modal.add_component(ar1)

            return event.reply(type=9, modal=modal)
        else:
            if event.data.custom_id != "agreement_submit":
                return

            username = None

            for action_row in event.data.components:
                for component in action_row.components:
                    if component.custom_id == "username":
                        username = component.value
                        break

            if username != event.member.user.username:
                return event.reply(type=4, content=Messages.creed_agreement_failed, flags=(1 << 6))

            try:
                event.guild.get_member(event.member.id).add_role(CONFIG.agreement.post_process_role, reason="Survivor's Creed signed! Assigned proper role!")
            except:
                self.log.error(f"Unable to add role to user who signed the Survivor's Creed. User ID {event.member.id}")
            Agreement.create(user_id=event.member.id, creed_agree=username)

            return event.reply(type=6)

    @Plugin.command("sendagreementmsg")
    def send_agreement_msg(self, event):
        # Moved message over to template file
        msg = Messages.agreement_message

        ar = ActionRow()

        button = MessageComponent()
        button.type = ComponentTypes.BUTTON
        button.style = ButtonStyles.SECONDARY
        button.emoji = None
        button.label = "Click to sign the Survivor's Creed"
        button.custom_id = "agreement_start"

        ar.add_component(button)

        event.channel.send_message(content=msg, components=[ar.to_dict()])
