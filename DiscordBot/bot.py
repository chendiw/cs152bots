# bot.py
import discord
from discord.ext import commands
import os
import json
import logging
import re
import requests
import random
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
        # This is has some security issues though
        if (responses[0] == "TRANSFER"):
            mod_channel = self.mod_channels[915746011757019217] # use a hack
            await mod_channel.send(f'User: `{responses[1]}` just reported user: `{responses[2]}`  with the following reason: `{responses[4]}`, specifically under fake account category, this user pretends to be `{responses[5]}` whose user name is: `{responses[3]}`\n')
            for i in range(5, len(responses)):
                await message.channel.send(responses[i])
            if responses[5] == "Myself":
                user_criteria = self.generate_sample_data(responses[1])
                reported_criteria = self.generate_sample_data(responses[2], reported=True, reported_reason=responses[4])
            else:
                user_criteria = self.generate_sample_data(responses[3])
                reported_criteria = self.generate_sample_data(responses[2], reported=True, reported_reason=responses[4])
            aggregate_criteria = {"0": user_criteria, "1": reported_criteria}
            print(aggregate_criteria)
            await mod_channel.send(f'{aggregate_criteria}\n\n')
            sus_score, unusual_report_counts = self.compute_sus_score(aggregate_criteria, user_report_react=True)
            await mod_channel.send(f'We have suspicious score calculated for the accounts as following\n {sus_score}. Those scores are specifically for impersonation.\n')
            await mod_channel.send(f'The following accounts have unusual high report counts\n {unusual_report_counts} on impersonation.\n')
            decision = self.decision_making(sus_score, unusual_report_counts)
            await mod_channel.send(f'We find the following accounts most likely to be fake accounts:\n {decision}\n')
            await mod_channel.send(f'Please type in the userid (case sensitive), and the action you want to take. Separated by comma, no space in between.\n')
        else:
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
        print(f"normal channel id {message.guild.id}")
        # await mod_channel.send(f'Forwarded message:\n{message.author.name}: "{message.content}"')
        
        # scores = self.eval_text(message)
        # await mod_channel.send(self.code_format(json.dumps(scores, indent=2)))
        accnts_criteria = self.batch_parse(message)
        await mod_channel.send(f'{accnts_criteria}\n\n')
        sus_score, unusual_report_counts = self.compute_sus_score(accnts_criteria)
        await mod_channel.send(f'We have suspicious score calculated for the accounts as following\n {sus_score}. Those scores are specifically for impersonation.\n')
        await mod_channel.send(f'The following accounts have unusual high report counts\n {unusual_report_counts} on impersonation.\n')
        decision = self.decision_making(sus_score, unusual_report_counts)
        await mod_channel.send(f'We find the following accounts most likely to be fake accounts:\n {decision}\n')
        await mod_channel.send(f'Please type in the userid (case sensitive), and the action you want to take. Separated by comma, no space in between.\n')

    async def handle_moderator_react(self, message):
        # Only handle messages sent in the "group-#-mod" channel
        # mainly parse the reaction of moderator on acount name, and action taken 
        if not message.channel.name == f'group-{self.group_num}-mod':
            return
        mod_channel = self.mod_channels[message.guild.id]
        moderator_res = message.content.split(',') # should be a list of [userid, action]
        if len(moderator_res) != 2:
            return
        if moderator_res[1] == "BAN":
            await mod_channel.send("\U0001F600")
            await mod_channel.send(f"Acount: {moderator_res[0]} is successfully banned from all users.")
        elif moderator_res[1] == "SUSPEND":
            await mod_channel.send("\U0001F601")
            await mod_channel.send(f"Acount: {moderator_res[0]} will be suspended for a month.")
        elif moderator_res[1] == "DEFER":
            await mod_channel.send(f"We defer our decision about Account: {moderator_res[0]} for more investigation.")
        else:
            await mod_channel.send(f"Please provide a valid reaction towards the account in question.")

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



    # ======================= Parse Direct Message to Group Channal of Multiple Similar Accounts ========================

    def parse_message(self, message):
        '''
        Default message fields: Name -> String, Intro -> String, Followers -> String[], Following -> String[], IP -> String
        Report Counts -> String, Reported reasons -> String, Latest reported by -> String
        Assume all field entries separated by semi-colon
        '''
        MAX_FIELDS = 7
        field_entries = message.split("; ")
        # if len(field_entries) > MAX_FIELDS:
        #     reply = "Ill-formed message: {}".format(message)
        #     await message.channel.send(reply)
        #     return
        fields = {}
        field_names = ["Name", "Intro", "Followers", "Following", "IP", "Report Counts", "Reported reasons"]
        for i in range(MAX_FIELDS):
            fields[field_names[i]] = field_entries[i]
            if field_names[i] == "IP":
                fields["lat-long"] = self.check_ip_location(fields["IP"])
        return fields

    def batch_parse(self, similar_accnts):
        # similar_accnts = json.loads(message.content)
        # similar_accnts = json.loads(message)
        accnts_criteria = {}
        for key, value in similar_accnts.items():
            accnts_criteria[key] = self.parse_message(value)
        return accnts_criteria



    # ======================================== Heuristics for Suspicious Score =============================================

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

    def dist_from_similar_accnts(self, cur_accnt, accnts_criteria, threshold, user_report_react=False):
        '''
        For cur_accnt:
        1. Compute its distance to all other similar accounts
        2. Compute how many times the distance exceeds our threshold
        3. If the count > |set_accnts|/2, flag cur_accnt
        '''
        if user_report_react:
            cur_lat_long = accnts_criteria["0"]["lat-long"]
            return int(self.dist_from_lat_long(cur_lat_long, accnts_criteria["1"]["lat-long"]) > threshold)
        else:
            cur_lat_long = accnts_criteria[cur_accnt]["lat-long"]
            exceed_cnt = 0
            for key, value in accnts_criteria.items():
                if key != cur_accnt:
                    exceed_cnt += int(self.dist_from_lat_long(cur_lat_long, accnts_criteria[key]["lat-long"]) > threshold)
            return int(exceed_cnt > (len(list(accnts_criteria.keys()))-1)/2)


    def check_followers(self, cur_accnt, accnts_criteria, user_report_react=False):
        '''
        For cur_accnt:
        1. If it has no followers or no following, flag
        2. If a lot of its followers are previously flagged, flag
        '''
        THRESHOLD = 5
        if user_report_react:
            cur_accnt = "1"
        followers_list = accnts_criteria[cur_accnt]["Followers"]
        following_list = accnts_criteria[cur_accnt]["Following"]
        flag = False
        if user_report_react:
            if (len(following_list) == 0) or (len(followers_list) == 0):
                flag = True
            else:
                with open("sample_accounts_state.json", "r") as db_f:
                    accnts_history = json.loads(db_f.read())
                    followers_flag = 0
                    followings_flag = 0
                    for i in followers_list:
                        if accnts_history[str(i)] == 1:
                            followers_flag += 1
                    for i in following_list:
                        if accnts_history[str(i)] == 1:
                            followings_flag += 1
                    if followers_flag > THRESHOLD or followings_flag > THRESHOLD:
                        flag = True
            return int(flag)

        m1 = re.search('([0-9]+)', followers_list)
        m2 = re.search('([0-9]+)', followers_list)
        if (not m1) or (not m2):
            flag = True
        return int(flag)

    def search_char_sub(self, cur_accnt, accnts_criteria, user_report_react=False):
        '''
        Referenced:
        https://www.ncbi.nlm.nih.gov/pmc/articles/PMC5614409/

        For cur_accnt:
        1. For each character, if it differs from half of the other similar accounts, search whether it's an intentional substitution
        2. If yes, increment count
        '''
        BLACKLIST = [
            set(['l', '1', 'L', '|', '!', 'I', '/', 'i']),
            set(['g', 'q', '9']),
            set(['m', 'n']),
            set(['u', 'v', 'U', 'V']),
            set(['c', 'e']),
            set(['b', '6']),
            set(['o', '0', 'O']),
            set(['Z', '2']),
            set(['B', '8'])
        ]

        if user_report_react:
            user_name = accnts_criteria["0"]["Name"]
            reported_name = accnts_criteria["1"]["Name"]
            sub_cnt = 0
            for i in range(min(len(user_name), len(reported_name))):
                if reported_name[i] != user_name[i]:
                    for s in BLACKLIST:
                        if user_name[i] in s:
                            sub_cnt += int(reported_name[i] in s)
                            break
            return int(sub_cnt > 0)
        else:
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

    def compute_sus_score(self, accnts_criteria, user_report_react=False):
        '''
        Sus score counts how many times an account is flagged in the following aspects:
        1. The account ip address is far from other similar accounts
        2. The account has less than 5 followers and the social network of the followers and following is closed
        3. Intentional blacklisted character substitution detected
        4. If the account is reported by the user, sus score += 1
        '''
        unusual_report_counts = []
        report_counts_benchmark = 1

        if user_report_react:
            sus_scores = {}
            cur_score = 0
            cur_score += self.dist_from_similar_accnts("0", accnts_criteria, 500, user_report_react)
            cur_score += self.check_followers("0", accnts_criteria, user_report_react)
            cur_score += self.search_char_sub("0", accnts_criteria, user_report_react)
            accnts_criteria["1"]["Report Counts"] += 1
            sus_scores[accnts_criteria["1"]["Name"]] = cur_score
            if int(accnts_criteria["1"]["Report Counts"]) >= report_counts_benchmark:
                unusual_report_counts.append(accnts_criteria["1"]["Name"])
        else:
            # set normal number of reports per user is <= 1
            sus_scores = {}
            for key, value in accnts_criteria.items():
                if accnts_criteria[key]['Reported reasons'] != "Impersonation":
                    continue
                cur_score = 0
                cur_score += self.dist_from_similar_accnts(key, accnts_criteria, 500)
                cur_score += self.check_followers(key, accnts_criteria)
                cur_score += self.search_char_sub(key, accnts_criteria)
                sus_scores[accnts_criteria[key]["Name"]] = cur_score
                if int(accnts_criteria[key]["Report Counts"]) >= report_counts_benchmark:
                    unusual_report_counts.append(accnts_criteria[key]["Name"])
        return sus_scores, unusual_report_counts


    def decision_making(self, sus_score, unusual_report_counts):
        '''
        Combine aggregated statistics on certain accounts to make decisions 
        on actions upon suspicious account activities
        '''
        accounts_to_look = []
        avg_sus = sum(sus_score.values())/ len(sus_score)
        for i,k in enumerate(sus_score.keys()):
            if sus_score[k] > avg_sus and unusual_report_counts[i]:
                accounts_to_look.append(k)
        return accounts_to_look

    # ======================= Simulate Account Data From User Report ========================

    def load_ip_addresses(self):
        input_files = ["lk.csv", "us.csv", "ve.csv"]
        with open("ip.json", "w") as ip_f:
            ip_by_country = {}
            for i in input_files:
                ip_by_country[i[:-4]] = []
                with open(i, "r") as f:
                    csv_reader = csv.reader(f)
                    for row in csv_reader:
                        if len(row) < 1:
                            continue
                        ip_by_country[i[:-4]].append(row[1])
            ip_f.write(json.dumps(ip_by_country))

    def construct_ip_address(self):
        with open("ip.json", "r") as ip_f:
            all_us = json.loads(ip_f.read())["us"]
        return all_us[random.randint(0, len(all_us)-1)]

    def sample_accounts_db(self, total_accnt, percentage_flagged):
        '''
        Simulate (in a larger db) some accounts have previously been flagged.
        If many of the followers of an account have been flagged, increment sus score by the followers field
        '''
        TOTAL_ACCNT = total_accnt
        PERCT_FLAGGED = percentage_flagged

        with open("sample_accounts_state.json", "w") as db_f:
            sample_accounts_state = {}
            for i in range(TOTAL_ACCNT):
                sample_accounts_state[i] = int(random.uniform(0, 1) < PERCT_FLAGGED)
            db_f.write(json.dumps(sample_accounts_state))

    def construct_followers(self, total_accnt):
        followers = set([])
        for i in range(random.randint(0, 50)):
            cur = random.randint(0, total_accnt-1)
            while cur in followers:
                cur = random.randint(0, total_accnt-1)
            followers.add(cur)
        return list(followers)

    def in_reports_log(self, username, reported, reported_reason):
        with open("report_log.json") as log_f:
            read = log_f.read()
            if len(read) == 0:
                return False, None
            log = json.loads(read)
            for k, v in log.items():
                if v["Name"] == username:
                    return True, k
        return False, None

    def generate_sample_data(self, account, reported=False, reported_reason="None"):
        '''
        Generate followers/following/ip address for reported and reporting user
        '''
        TOTAL_ACCNT = 1000
        PERCT_FLAGGED = 0.02

        prev_reported, k = self.in_reports_log(account, reported, reported_reason)
        with open("report_log.json", "r") as log_f:
            read = log_f.read()
            if len(read) != 0:
                log = json.loads(read)
            else:
                log = {}

        if not prev_reported:
            if len(list(log.keys())) > 0:
                new_id = int(list(log.keys())[-1])+1
            else:
                new_id = 0

            fields = {}
            field_names = ["Name", "Followers", "Following", "IP", "Report Counts", "Reported reasons"]
            for i in range(len(field_names)):
                if field_names[i] == "Name":
                    fields[field_names[i]] = account
                if field_names[i] == "Followers":
                    fields[field_names[i]] = self.construct_followers(TOTAL_ACCNT)
                if field_names[i] == "Following":
                    fields[field_names[i]] = self.construct_followers(TOTAL_ACCNT)
                if field_names[i] == "IP":
                    fields["IP"] = self.construct_ip_address()
                    fields["lat-long"] = self.check_ip_location(fields["IP"])
                if field_names[i] == "Report Counts":
                    fields[field_names[i]] = int(reported)
                if field_names[i] == "Reported reasons":
                    fields[field_names[i]] = [reported_reason]

            log[new_id] = fields
        else:
            log[k]["Report Counts"] += int(reported)
            if reported:
                log[k]["Reported reasons"].append(reported_reason)
            fields = log[k]

        with open("report_log.json", "w") as log_f:
            log_f.write(json.dumps(log))

        return fields
        

client = ModBot(perspective_key, ip_checker_key)
client.run(discord_token)
