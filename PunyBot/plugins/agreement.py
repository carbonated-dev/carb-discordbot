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

            if CONFIG.agreement.pre_process_role not in event.member.roles or CONFIG.agreement.post_process_role in event.member.roles:
                return event.reply(type=6)

            creed_agree = MessageComponent()
            creed_agree.type = ComponentTypes.TEXT_INPUT
            creed_agree.style = TextInputStyles.SHORT
            creed_agree.label = "Do you swear by the Survivor's Creed?"
            creed_agree.placeholder = "I swear!"
            creed_agree.required = True
            creed_agree.custom_id = "creed_agree"

            ar1 = ActionRow()
            ar1.add_component(creed_agree)

            modal = MessageModal()
            modal.title = "Survivor's Creed"
            modal.custom_id = "agreement_submit"
            modal.add_component(ar1)

            return event.reply(type=9, modal=modal)
        else:
            if event.data.custom_id != "agreement_submit":
                return

            creed_agree = None

            for action_row in event.data.components:
                for component in action_row.components:
                    if component.custom_id == "creed_agree":
                        first_name = component.value
                        break

            try:
                guild = self.client.state.guilds[event.guild.id]

                tmp_roles = event.member.roles
                tmp_roles.remove(CONFIG.agreement.pre_process_role)
                tmp_roles.append(CONFIG.agreement.post_process_role)

                guild.get_member(event.member.id).modify(roles=tmp_roles, reason="Survivor's Creed signed! Assigning proper role!")
            except:
                self.log.error(f"Unable to add role to user who signed the Survivor's Creed. User ID {event.member.id}")
            Agreement.create(user_id=event.member.id, first_name=first_name, last_name=last_name)

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
