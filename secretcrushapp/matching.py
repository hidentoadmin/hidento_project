import logging
import threading

from django.db import transaction
from django.utils.timezone import now

from hidento_project import settings

logging.basicConfig(filename=settings.LOG_FILE_PATH, level=logging.DEBUG)
def startMatching(user, stage, losersSet, latestUser):
    if user is None or ((stage == 3 or stage == 4) and user == latestUser):
        logging.debug('Latest User - {} is trying make match at stage - {}. Stopping the cycle.'.format(user, stage))
        return
    with transaction.atomic():
        from secretcrushapp.models import InstagramCrush
        try:
            user_instagram = user.instagramDetails.select_for_update().first()
        except InstagramCrush.DoesNotExist:
            return
        firstLoser = None
        if currentMatchRemoved(user_instagram):
            firstLoser = breakCurrentMatch(user_instagram)
        newOrBetterMatchAvailable = tryToMakeNewMatch(user_instagram)
        if newOrBetterMatchAvailable is not None:
            if stage == 2:
                latestUser = getLatestUser(user, newOrBetterMatchAvailable.hidento_userid, latestUser)
            if newOrBetterMatchAvailable.hidento_userid in losersSet:
                if stage == 1:
                    logging.debug('Cycle detected at stage 1 at user - {}'.format(newOrBetterMatchAvailable.hidento_userid))
                if stage == 2:
                    logging.debug('Latest User found - {}'.format(latestUser))
                losersSet=set()
                stage += 1
                logging.debug('Entering stage - {}'.format(stage))
            losers = makeMatch(user_instagram, newOrBetterMatchAvailable)
            if losers[0] is not None:
                firstLoser = losers[0]
            secondLoser = losers[1]
            newOrBetterMatchAvailable.save()
            if secondLoser is not None:
                secondLoser.save()
                losersSet.add(secondLoser.hidento_userid)
                secondLoserThread = threading.Thread(target=startMatching, daemon=True, args=(secondLoser.hidento_userid, stage, losersSet, latestUser))
                secondLoserThread.start()
        user_instagram.save()
        if firstLoser is not None:
            firstLoser.save()
            firstLoserThread = threading.Thread(target=startMatching, daemon=True, args=(firstLoser.hidento_userid, 1, {firstLoser.hidento_userid}, None))
            firstLoserThread.start()

def makeMatch(user_instagram, crushToMatch):
    match_time = now()
    useOldMatchTime = isNewMatchSameAsOldAndWithinOneHourOfBrokenTime(user_instagram, crushToMatch.instagram_username, match_time)
    firstLoser = breakCurrentMatch(user_instagram)
    secondLoser = breakCurrentMatch(crushToMatch)
    crushToMatch.match_instagram_username = user_instagram.instagram_username
    user_instagram.match_instagram_username = crushToMatch.instagram_username
    if useOldMatchTime is not None:
        user_instagram.match_time = useOldMatchTime
        crushToMatch.match_time = useOldMatchTime
    else:
        user_instagram.match_time = match_time
        crushToMatch.match_time = match_time
    return (firstLoser, secondLoser)

def isNewMatchSameAsOldAndWithinOneHourOfBrokenTime(user_instagram, new_instagram_username, match_time):
    if user_instagram.old_match_instagram_username is not None \
        and user_instagram.old_match_instagram_username == new_instagram_username \
        and oldMatchBrokenLessThanOneHourBefore(user_instagram.old_match_broken_time, match_time):
        return user_instagram.old_match_time
    return None

def oldMatchBrokenLessThanOneHourBefore(broken_time, now_time):
    time_difference = now_time - broken_time
    duration_in_minutes = divmod(time_difference.total_seconds(), 60)[0]
    if duration_in_minutes <= 60:
        return True
    return False

def getCrushPosition(user_instagram, crushUsername):
    for position in range(1,6):
        if user_instagram.__dict__[getCrushField(position, 'username')] == crushUsername:
            return position
    return 0

def currentMatchRemoved(user_instagram):
    if user_instagram.match_instagram_username is not None and currentMatchPriorityPosition(user_instagram) == 0:
        return True
    return False

def breakCurrentMatch(user_instagram):
    if user_instagram.match_instagram_username is None:
        return None
    from secretcrushapp.models import InstagramCrush
    try:
        matchToBreak = InstagramCrush.objects.select_for_update().get(instagram_username=user_instagram.match_instagram_username)
    except InstagramCrush.DoesNotExist:
        matchToBreak = None
    breaking_time = now()
    if matchToBreak is not None:
        matchToBreak.match_instagram_username = None
        matchToBreak.match_time = None
    user_instagram.old_match_instagram_username = user_instagram.match_instagram_username
    user_instagram.old_match_time = user_instagram.match_time
    user_instagram.old_match_broken_time = breaking_time
    user_instagram.match_instagram_username = None
    user_instagram.match_time = None
    return matchToBreak

def tryToMakeNewMatch(user_instagram):
    if user_instagram is None or user_instagram.match_stablized:
        return None
    for position in range(1,6):
        crushUsername = user_instagram.__dict__[getCrushField(position, 'username')]
        crushIsActive = user_instagram.__dict__[getCrushField(position, 'active')]
        if crushUsername is not None and crushIsActive:
            from secretcrushapp.models import InstagramCrush
            try:
                crushInstagram = InstagramCrush.objects.select_for_update().get(instagram_username=crushUsername)
            except InstagramCrush.DoesNotExist:
                continue
            if crushIsAvailableForMatch(crushInstagram, user_instagram.instagram_username):
                if user_instagram.match_instagram_username is None or position < currentMatchPriorityPosition(user_instagram):
                    return crushInstagram
                return None
    return None

def crushIsAvailableForMatch(crushInstagram, user_instagram_username):
    if crushInstagram is None or crushInstagram.match_stablized:
        return False
    for position in range(1,6):
        crushscrushUsername = crushInstagram.__dict__[getCrushField(position, 'username')]
        crushscrushIsActive = crushInstagram.__dict__[getCrushField(position, 'active')]
        if crushscrushUsername is not None and crushscrushIsActive:
            if crushscrushUsername == user_instagram_username:
                if crushInstagram.match_instagram_username is None or position <= currentMatchPriorityPosition(crushInstagram):
                    return True
                return False
    return False

def currentMatchPriorityPosition(user_instagram):
    for position in range(1,6):
        if user_instagram.__dict__[getCrushField(position, 'username')] == user_instagram.match_instagram_username \
                and user_instagram.__dict__[getCrushField(position, 'active')]:
            return position
    return 0

def getCrushField(position, fieldname):
    return 'crush' + str(position) + '_' + fieldname

def getLatestUser(user1, user2, user3):
    if user1.joined_time > user2.joined_time:
        latestUser = user1
    else:
        latestUser = user2
    if user3 is not None:
        if user3.joined_time > latestUser.joined_time:
            latestUser = user3
    return latestUser