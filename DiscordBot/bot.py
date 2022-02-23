# bot.py
import discord
from discord.ext import commands
import os
import json
import logging
import re
import requests
from report import Report
from math import radians, cos, sin, asin, sqrt

# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# There should be a file called 'token.json' inside the same folder as this file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    # If you get an error here, it means your token is formatted incorrectly. Did you put it in quotes?
    tokens = json.load(f)
    discord_token = tokens['discord']
    perspective_key = tokens['perspective']
    ip_checker_key = tokens['ip_checker']


class ModBot(discord.Client):
    def __init__(self, perspective_key, ip_checker_key):
        intents = discord.Intents.default()
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {} # Map from guild to the mod channel id for that guild
        self.reports = {} # Map from user IDs to the state of their report
        self.perspective_key = perspective_key
        self.ip_checker_key = ip_checker_key

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        # Parse the group number out of the bot's name
        match = re.search('[gG]roup (\d+) [bB]ot', self.user.name)
        if match:
            self.group_num = match.group(1)
        else:
            raise Exception("Group number not found in bot's name. Name format should be \"Group # Bot\".")

        # Find the mod channel in each guild that this bot should report to
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-{self.group_num}-mod':
                    self.mod_channels[guild.id] = channel

    async def on_message(self, message):
        '''
        This function is called whenever a message is sent in a channel that the bot can see (including DMs). 
        Currently the bot is configured to only handle messages that are sent over DMs or in your group's "group-#" channel. 
        '''
        # Ignore messages from the bot 
        if message.author.id == self.user.id:
            return
        # name='group-42', name='group-42-mod'
        # Check if this message was sent in a server ("guild") or if it's a DM
        if message.guild:
            if message.channel.name == f'group-{self.group_num}':
                await self.handle_channel_message(message)
            if message.channel.name == f'group-{self.group_num}-mod':
                await self.handle_moderator_react(message)
                
        else:
            await self.handle_dm(message)

    async def handle_dm(self, message):
        # Handle a help message
        if message.content == Report.HELP_KEYWORD:
            reply =  "Use the `report` command to begin the reporting process.\n"
            reply += "Use the `cancel` command to cancel the report process.\n"
            await message.channel.send(reply)
            return

        author_id = message.author.id
        responses = []

        # Only respond to messages if they're part of a reporting flow
        if author_id not in self.reports and not message.content.startswith(Report.START_KEYWORD):
            return

        # If we don't currently have an active report for this user, add one
        if author_id not in self.reports:
            self.reports[author_id] = Report(self)

        # Let the report class handle this message; forward all the messages it returns to uss
        responses = await self.reports[author_id].handle_message(message)
        for r in responses:
            await message.channel.send(r)

        # If the report is complete or cancelled, remove it from our map
        if self.reports[author_id].report_complete():
            self.reports.pop(author_id)

    async def handle_channel_message(self, message):
        # Only handle messages sent in the "group-#" channel
        if not message.channel.name == f'group-{self.group_num}':
            return

        # Forward the message to the mod channel
        mod_channel = self.mod_channels[message.guild.id]
        await mod_channel.send(f'Forwarded message:\n{message.author.name}: "{message.content}"')

        # scores = self.eval_text(message)
        # await mod_channel.send(self.code_format(json.dumps(scores, indent=2)))

        sus_score, unusual_report_counts = self.compute_sus_score(message)
        await mod_channel.send(f'We have suspicious score calculated for the accounts as following\n {sus_score}')
        await mod_channel.send(f'The following accounts have unusual high report counts\n {unusual_report_counts}')
        await mod_channel.send(f'Based on the aggregated stats, on which account you would like to take an action?')
        await mod_channel.send(f'Please type in the userid, and the action you want to take. Separated by comma, no space in between.')

    async def handle_moderator_react(self, message):
        # Only handle messages sent in the "group-#-mod" channel
        # mainly parse the reaction of moderator on acount name, and action taken 
        if not message.channel.name == f'group-{self.group_num}-mod':
            return
        mod_channel = self.mod_channels[message.guild.id]
        moderator_res = message.content.split(',') # should be a list of [userid, action]
        
        if moderator_res[1] == "BAN":
            await mod_channel.send("\U0001F600")
        elif moderator_res[1] == "SUSPEND":
            await mod_channel.send("\U0001F601")
        
    def eval_text(self, message):
        '''
        Given a message, forwards the message to Perspective and returns a dictionary of scores.
        '''
        PERSPECTIVE_URL = 'https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze'

        url = PERSPECTIVE_URL + '?key=' + self.perspective_key
        data_dict = {
            'comment': {'text': message.content},
            'languages': ['en'],
            'requestedAttributes': {
                                    'SEVERE_TOXICITY': {}, 'PROFANITY': {},
                                    'IDENTITY_ATTACK': {}, 'THREAT': {},
                                    'TOXICITY': {}, 'FLIRTATION': {}
                                },
            'doNotStore': True
        }
        response = requests.post(url, data=json.dumps(data_dict))
        response_dict = response.json()

        scores = {}
        for attr in response_dict["attributeScores"]:
            scores[attr] = response_dict["attributeScores"][attr]["summaryScore"]["value"]

        return scores

    def code_format(self, text):
        return "```" + text + "```"

    def parse_message(self, message):
        '''
        Default message fields: Name -> String, Intro -> String, Followers -> String[], Following -> String[], IP -> String
        Assume all field entries separated by semi-colon
        '''
        MAX_FIELDS = 6
        field_entries = message.split(";")
        # if len(field_entries) > MAX_FIELDS:
        #     reply = "Ill-formed message: {}".format(message)
        #     await message.channel.send(reply)
        #     return
        fields = {}
        field_names = ["Name", "Intro", "Followers", "Following", "IP", "Report Counts"]
        for i in range(MAX_FIELDS):
            fields[field_names[i]] = field_entries[i]
            if field_names[i] == "IP":
                fields["lat-long"] = self.check_ip_location(fields["IP"])
        return fields

    def check_ip_location(self, ip):
        '''
        Retrieve zipcode, latitude and longitude data from the ip address
        '''
        IP_GEO_URL = 'https://api.ipgeolocation.io/ipgeo'

        params = (
            ('apiKey', self.ip_checker_key),
            ('ip', ip),
            ('fields', 'city,zipcode,latitude,longitude'),
        )

        response = requests.get(IP_GEO_URL, params=params).json()
        return (response["latitude"], response["longitude"])

    def dist_from_lat_long(self, lat_long_1, lat_long_2):
        '''
        Referenced:
        https://www.geeksforgeeks.org/program-distance-two-points-earth/#:~:text=For%20this%20divide%20the%20values,is%20the%20radius%20of%20Earth.
        Return value in miles
        '''
        lat1, lon1 = float(lat_long_1[0]), float(lat_long_1[1])
        lat2, lon2 = float(lat_long_2[0]), float(lat_long_2[1]) 
        lon1 = radians(lon1)
        lon2 = radians(lon2)
        lat1 = radians(lat1)
        lat2 = radians(lat2)

        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = sin(dlat / 2)**2 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2
        c = 2 * asin(sqrt(a))

        # Radius of earth in miles
        r = 3956
        return(c * r)

    def dist_from_similar_accnts(self, cur_accnt, accnts_criteria, threshold):
        '''
        For cur_accnt:
        1. Compute its distance to all other similar accounts
        2. Compute how many times the distance exceeds our threshold
        3. If the count > |set_accnts|/2, flag cur_accnt
        '''
        cur_lat_long = accnts_criteria[cur_accnt]["lat-long"]
        exceed_cnt = 0
        for key, value in accnts_criteria.items():
            if key != cur_accnt:
                exceed_cnt += int(self.dist_from_lat_long(cur_lat_long, accnts_criteria[key]["lat-long"]) > threshold)
        return int(exceed_cnt > (len(list(accnts_criteria.keys()))-1)/2)


    def check_followers(self, cur_accnt, accnts_criteria):
        '''
        For cur_accnt:
        1. If it has no followers or no following, flag
        2. Check closed cycle (TODO)
        '''
        followers_list = accnts_criteria[cur_accnt]["Followers"]
        m1 = re.search('([0-9]+)', followers_list)
        if not m1:
            return 1
        following_list = accnts_criteria[cur_accnt]["Following"]
        m2 = re.search('([0-9]+)', followers_list)
        if not m2:
            return 1
        return 0

    def search_char_sub(self, cur_accnt, accnts_criteria):
        '''
        Referenced:
        https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5614409/

        For cur_accnt:
        1. For each character, if it differs from half of the other similar accounts, search whether it's an intentional substitution
        2. If yes, increment count
        '''
        BLACKLIST = [
            set(['l', '1', 'L', '|', '!', 'I', '/']),
            set(['g', 'q', '9']),
            set(['m', 'n']),
            set(['u', 'v', 'U', 'V']),
            set(['c', 'e']),
            set(['b', '6']),
            set(['o', '0', 'O']),
            set(['Z', '2']),
            set(['B', '8'])
        ]

        sub_cnt = 0
        cur_name = accnts_criteria[cur_accnt]["Name"]
        for i in range(len(cur_name)):
            cur_char = cur_name[i]
            diff = 0
            common_char = {}
            for key, value in accnts_criteria.items():
                if i >= len(value["Name"]):
                    continue
                if key != cur_accnt and value["Name"][i] != cur_char:
                    diff += 1
                    if value["Name"][i] not in common_char.keys():
                        common_char[value["Name"][i]] = 1
                    else:
                        common_char[value["Name"][i]] += 1
            common_char_list = list(common_char.items())
            common_char_list.sort(key = lambda x : x[1], reverse=True)

            if diff > len(list(accnts_criteria.keys())) / 2:
                for s in BLACKLIST:
                    if common_char_list[0][0] in s:
                        sub_cnt += int(cur_char in s)
                        break
        return int(sub_cnt > 0)

    def compute_sus_score(self, message):
        '''
        Sus score counts how many times an account is flagged in the following aspects:
        1. The account ip address is far from other similar accounts
        2. The account has less than 5 followers and the social network of the followers and following is closed
        3. Intentional blacklisted character substitution detected
        '''
        similar_accnts = json.loads(message.content)
        accnts_criteria = {}
        for key, value in similar_accnts.items():
            accnts_criteria[key] = self.parse_message(value)
       
        unusual_report_counts = {}
        # set normal number of reports per user is <= 1
        report_counts_benchmark = 1
        sus_scores = {}
        for key, value in accnts_criteria.items():
            cur_score = 0
            cur_score += self.dist_from_similar_accnts(key, accnts_criteria, 500)
            cur_score += self.check_followers(key, accnts_criteria)
            cur_score += self.search_char_sub(key, accnts_criteria)
            sus_scores[key] = cur_score
            if int(accnts_criteria[key]["Report Counts"]) > report_counts_benchmark:
                unusual_report_counts[key] = True
            else:
                unusual_report_counts[key] = False
        return sus_scores, unusual_report_counts


    def decision_making(self, username):
        '''
        Combine aggregated statistics on certain accounts to make decisions 
        on actions upon suspicious account activities
        '''
        


client = ModBot(perspective_key, ip_checker_key)
client.run(discord_token)
