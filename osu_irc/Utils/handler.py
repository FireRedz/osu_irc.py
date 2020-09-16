from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..Classes.client import Client

# from ..Classes.message import Message
# from .message import Message

import logging
Log:logging.Logger = logging.getLogger("osu_irc")

import re
import asyncio
from ..Classes.channel import Channel
from ..Classes.user import User
from ..Utils.regex import ReUserListData, ReQuit

async def handleJoin(cls:"Client", payload:str) -> bool:
	"""
	handles all JOIN events

	may calls the following events for custom code:
	- onMemberJoin(Channel, User)
	"""
	JoinUser = User(payload)

	# ignore self, but use it to update the clients channels
	if JoinUser.name.lower() == cls.nickname.lower():

		FreshChannel:Channel = Channel(None)
		FreshChannel._name = JoinUser._generated_via_channel

		# add new channel to clients known channels
		Log.debug(f"Client joined a channel, adding {JoinUser._generated_via_channel}")
		cls.channels[FreshChannel.name] = FreshChannel

		return True

	# let's see if we got this user already
	KnownUser:User = cls.users.get(JoinUser.name, None)
	if not KnownUser:
		# we never saw this user, add it
		cls.users[JoinUser.name] = JoinUser
		KnownUser = cls.users[JoinUser.name]

	Chan:Channel = cls.channels.get(JoinUser._generated_via_channel, None)
	if not Chan:
		# that should never happen... but if it does... well fuck
		Log.error(f"Could not find channel for {JoinUser._generated_via_channel}")
		return True

	# add User to chatters dict of channel
	Chan.chatters[KnownUser.name] = KnownUser
	# add add channel id to Users known channels
	KnownUser.found_in.add(Chan.name)

	Log.debug(f"Client launching: Client.onMemberJoin: {str(vars(Chan))} {str(vars(KnownUser))}")
	asyncio.ensure_future( cls.onMemberJoin(Chan, KnownUser) )
	return True

async def handlePart(cls:"Client", payload:str) -> bool:
	"""
	handles all PART events

	may calls the following events for custom code:
	- onMemberPart(Channel, User)
	"""
	PartUser:User = User(payload)

	# ignore self but use it to update clients channel dict
	if PartUser.name.lower() == cls.nickname.lower():

		# if we got a part for our user... well guess we can delete the channel then, right?
		Log.debug(f"Client parted a channel, removing {PartUser._generated_via_channel}")
		cls.channels.pop(PartUser._generated_via_channel, None)

		return True

	# let's see if we got this user already
	KnownUser:User = cls.users.get(PartUser.name, None)
	if not KnownUser:
		# we never saw this user, even duh we got a leave.
		KnownUser = PartUser

	Chan:Channel = cls.channels.get(PartUser._generated_via_channel, None)
	if not Chan:
		# that should never happen... but if it does... well fuck
		Log.error(f"Could not find channel for {PartUser._generated_via_channel}")
		return True

	# remove User from chatters dict of channel
	Chan.chatters.pop(KnownUser.name, None)
	# and remove it from the Users known channels
	KnownUser.found_in.discard(Chan.name)

	# the user left the last channel we monitor, he now is useless for us
	if len(KnownUser.found_in) == 0:
		cls.users.pop(KnownUser.name, None)

	Log.debug(f"Client launching: Client.onMemberPart: {str(vars(Chan))} {str(vars(KnownUser))}")
	asyncio.ensure_future( cls.onMemberPart(Chan, KnownUser) )
	return True

async def handleQuit(cls:"Client", payload:str) -> bool:
	"""
	handles all QUIT events, an ooo boi there a lot of them
	this happens when a user closes the game, or a client disconnects by any means from the irc server
	mostly this happens instantly with the reason: quit
	or some time later with a timeout.

	However, a user that quits will be deleted from all other channels, but there will not me a PART for every channel

	may calls the following events for custom code:
	- onMemberQuit(User, reason)
	:Fenix005!cho@ppy.sh QUIT :quit
	"""

	# name and reason
	search = re.search(ReQuit, payload)
	if search == None:
		# in case we don't find anything, just ignore it, just you should with all problems in life :3
		return True

	user_name:str = search.group(1)
	reason:str = search.group(2)

	QuitingUser:User = cls.users.get(user_name, None)
	if not QuitingUser:
		QuitingUser = User(None)
		QuitingUser._name = user_name
	else:
		# remove quiting user from all channel.chatters dict's
		for channel_name in QuitingUser.found_in:
			Chan:Channel = cls.channels.get(channel_name, None)
			if not Chan: continue
			Chan.chatters.pop(QuitingUser.name, None)

		# and also remove it from clients user storage, which then should delete user object completly from memory
		cls.users.pop(QuitingUser.name, None)

	Log.debug(f"Client launching: Client.onMemberQuit: {str(vars(QuitingUser))} {reason}")
	asyncio.ensure_future( cls.onMemberQuit(QuitingUser, reason) )
	return True

async def handleUserList(cls:"Client", payload:str) -> bool:
	"""
	User-List aka, IRC Event: 353
	which means a list of all users that already are in the channel when the Client joined.

	may calls the following events for custom code:
	- None
	"""

	# e.g.: :cho.ppy.sh 353 Phaazebot = #osu :The_CJ SomeoneElse +SomeoneViaIRC @SomeModerator
	search:re.Match = re.search(ReUserListData, payload)
	if search != None:
		room_name:str = search.group(1)
		ChannelToFill:Channel = cls.channels.get(room_name, None)
		if not ChannelToFill: return True

		full_user_list:str = search.group(2)
		for user_name in full_user_list.split(' '):

			# for whatever reason, osu! likes giving empty cahrs at the end... thanks i guess?
			if user_name.lower() in ['', ' ', cls.nickname.lower()]: continue

			# check user type and change name, also add to usertype set
			if user_name.startswith('~'):
				user_name = user_name[1:]
				ChannelToFill._owner.add(user_name)
			if user_name.startswith('&'):
				user_name = user_name[1:]
				ChannelToFill._admin.add(user_name)
			if user_name.startswith('@'):
				user_name = user_name[1:]
				ChannelToFill._operator.add(user_name)
			if user_name.startswith('%'):
				user_name = user_name[1:]
				ChannelToFill._helper.add(user_name)
			if user_name.startswith('+'):
				user_name = user_name[1:]
				ChannelToFill._voiced.add(user_name)

			KnownUser:User = cls.users.get(user_name, None)
			if not KnownUser:
				KnownUser:User = User(None)
				KnownUser._name = user_name

				cls.users[KnownUser.name] = KnownUser

			Log.debug(f"New Entry to `already-known-user-list`: {ChannelToFill.name} - {KnownUser.name}")
			ChannelToFill.chatters[KnownUser.name] = KnownUser
			KnownUser.found_in.add(ChannelToFill.name)

	return True

async def handlePrivMessage(cls:"Client", payload:str) -> bool:
	"""
	handles all PRIVMSG events

	may calls the following events for custom code:
	- onMessage(Message)
	"""
	return True
