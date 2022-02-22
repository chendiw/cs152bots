from enum import Enum, auto
import discord
import re

class State(Enum):
    REPORT_START = auto()
    AWAITING_MESSAGE = auto()
    MESSAGE_IDENTIFIED = auto()
    REPORT_COMPLETE = auto()
    WHY_REPORT_ACCNT = auto()
    FAKE_ACCNT_IDENTIFIED = auto()
    MYSELF_IDENTIFIED = auto()
    THIRD_PARTY_IDENTIFIED = auto()
    TO_BLOCK = auto()


class Report:
    START_KEYWORD = "report"
    CANCEL_KEYWORD = "cancel"
    HELP_KEYWORD = "help"

    # Options for report reason
    REPORT_REASON_DICT = {'A': "Monetary loss due to interaction with this account", 
                        'B': "It's posting content that shouldn't be on Instagram",
                        'C': "It's pretending to be someone else",
                        'D': "It may be under the age of 13",
                        'E': "Other reasons and a moderator will review your case."}

    # Options for fake account type
    FAKE_ACCNT_TYPE_DICT = {'A': "Myself",
                            'B': "Someone I know", 
                            'C': "A celebrtty or public figure",
                            'D': "A business or organization"}

    # Options for reporting a fake account pretending to be the user themselves
    RESPONSE_MYSELF_DICT = {'A': "Pirating my photo for its profile or posts.", 
                            'B': "Messaging others on my behalf.", 
                            'C': "Making improper comments on my behalf."}

    def __init__(self, client):
        self.state = State.REPORT_START
        self.client = client
        self.message = None
        self.fake_accnt_type = None
        self.sus_behavior = []
        self.third_party_username = None
        self.block = False

    
    async def handle_message(self, message):
        '''
        This function makes up the meat of the user-side reporting flow. It defines how we transition between states and what 
        prompts to offer at each of those states. You're welcome to change anything you want; this skeleton is just here to
        get you started and give you a model for working with Discord. 
        '''

        if message.content == self.CANCEL_KEYWORD:
            self.state = State.REPORT_COMPLETE
            return ["Report cancelled."]
        
        if self.state == State.REPORT_START:
            reply =  "Thank you for starting the reporting process. "
            reply += "Say `help` at any time for more information.\n\n"
            reply += "Please copy paste the link to the message you want to report.\n"
            reply += "You can obtain this link by right-clicking the message and clicking `Copy Message Link`."
            self.state = State.AWAITING_MESSAGE
            return [reply]
        
        if self.state == State.AWAITING_MESSAGE:
            # Parse out the three ID strings from the message link
            m = re.search('/(\d+)/(\d+)/(\d+)', message.content)
            if not m:
                return ["I'm sorry, I couldn't read that link. Please try again or say `cancel` to cancel."]
            guild = self.client.get_guild(int(m.group(1)))
            if not guild:
                return ["I cannot accept reports of messages from guilds that I'm not in. Please have the guild owner add me to the guild and try again."]
            channel = guild.get_channel(int(m.group(2)))
            if not channel:
                return ["It seems this channel was deleted or never existed. Please try again or say `cancel` to cancel."]
            try:
                message = await channel.fetch_message(int(m.group(3)))
            except discord.errors.NotFound:
                return ["It seems this message was deleted or never existed. Please try again or say `cancel` to cancel."]

            # Here we've found the message - it's up to you to decide what to do next!
            # self.state = State.MESSAGE_IDENTIFIED
            self.state = State.WHY_REPORT_ACCNT
            reply = "I found this message:" + "```" + message.author.name + ": " + message.content + "```" + "\n"
            reply += "Why are you reporting this account? (case insensitive)\n"
            for k, v in self.REPORT_REASON_DICT.items():
                reply += "Reply {} for {}\n".format(k, v)
            return [reply]
        
        if self.state == State.WHY_REPORT_ACCNT:
            m = re.search('([ABCDE|abcde])', message.content)
            if not m:
                return ["I'm sorry, I couldn't read the response. Please reply a single letter or say 'cancel' to cancel."]
            response = m.group(1).upper()
            if response != 'C':
                self.report_complete()
                return ["A member of the team will investigate your case. Thanks for reporting."]
            else:
                self.state = State.FAKE_ACCNT_IDENTIFIED
                reply = "We'd like to know more. Who is this account pretending to be?\n"
                for k, v in self.FAKE_ACCNT_TYPE_DICT.items():
                    reply += "Reply {} for {}\n".format(k, v)
                return [reply]

        if self.state == State.FAKE_ACCNT_IDENTIFIED:
            m = re.search('([ABCD|abcd])', message.content)
            if not m:
                return ["I'm sorry, I couldn't read the response. Please reply a single letter or say 'cancel' to cancel."]
            response = m.group(1).upper()
            self.fake_accnt_type = self.FAKE_ACCNT_TYPE_DICT[response]
            if response == 'A':
                self.state = State.MYSELF_IDENTIFIED
                reply = "What are the suspicious behavior? Multiple choice if applicable.\n"
                for k, v in self.RESPONSE_MYSELF_DICT.items():
                    reply += "Reply {} for {}\n".format(k, v)
                return [reply]
            else:
                self.state = State.THIRD_PARTY_IDENTIFIED
                return ["Whose account is this account pretending to be?", \
                        "Please respond with the username: (Default to None)"]

        if self.state == State.MYSELF_IDENTIFIED:
            m = re.search('([ABC|abc]+)', message.content)
            if not m:
                return ["I'm sorry, I couldn't read the response. Please reply a single letter or say 'cancel' to cancel."]
            response_letter = m.group(1).upper()
            self.sus_behavior = list(response_letter)
            print("Sus behavior list: {}".format(self.sus_behavior))
            reply = "Thank you for reporting. Our content moderation team will review your report. \
            This may result in the reported account suspension, shadowblock, or removal. \
            You will hear back about our decision regarding this report in the next few weeks. \n\n \
            Do you want us to block this account from any future interaction with you?"
            self.state = State.TO_BLOCK
            return [reply]

        if self.state == State.THIRD_PARTY_IDENTIFIED:
            self.third_party_username = message.content
            print("Third party names: {}".format(self.third_party_username))
            reply = "Thank you for reporting. Our content moderation team will review your report. This may result in the reported account suspension, shadowblock, or removal. You will hear back about our decision regarding this report in the next few weeks. \n\n \
            Do you want us to block this account from any future interaction with you? \n Y for yes. N for no."
            self.state = State.TO_BLOCK
            return [reply]

        if self.state == State.TO_BLOCK:
            m = re.search('([Yy|Nn])', message.content)
            if not m:
                return ["I'm sorry, I couldn't read the response. Please reply a single letter or say 'cancel' to cancel."]
            if m.group(1).upper() == 'Y':
                self.block = True 
                return ["Reported account banned."]
            else:
                return ["Reported account not banned."]
            

        return []

    def report_complete(self):
        return self.state == State.REPORT_COMPLETE
    


    

