#!/usr/bin/env python
#
# This program is a Youtube Client for the AigoLearning video management
# project.
#
#
# Dependency:
# Need to run this problem with python 3.11+
# pip3 install --upgrade google-api-python-client oauth2client
#
# TODO(jackwaashere): add more documentation
#
# The OAuth2 part code uses the library from another project at
# https://github.com/tokland/youtube-upload
# Author: Arnau Sanchez <pyarnau@gmail.com>


import os
import sys
import optparse
import json
from io import open
import csv

import googleapiclient.errors

import auth
from auth import lib

from thinkland import classes
from thinkland.classes import log
from thinkland.classes import appendProcessedVideo


unprocessed_playlist = 'PLzr1p9rMdhyAPAN1c6O-AeoJPUk4LkQj2'
error_processing_playlist = 'PLzr1p9rMdhyCZ-wxUPEUy7plgIWP_l-cI'

#unprocessed_playlist = 'PLLoERmYbGOUn9r9pAke-3_pj-kEEj9cpl'
#error_processing_playlist = 'PLLoERmYbGOUkL5PX69LpM4bUiMYjhzOk2'

DAILY_THRESHOLD = 9500
UNPROCESSED_LIMIT = 42
NEXT_PAGE_TOKEN = "EAAaBlBUOkNESQ"

class AuthenticationError(Exception): pass

class RequestError(Exception): pass

def get_youtube_handler(options):
    """Return the API Youtube object."""
    home = os.path.expanduser("~")
    default_credentials = os.path.join(home, ".youtube-upload-credentials.json")
    client_secrets = options.client_secrets or os.path.join(home, ".client_secrets.json")
    credentials = options.credentials_file or default_credentials
    lib.debug("Using client secrets: {0}".format(client_secrets))
    lib.debug("Using credentials file: {0}".format(credentials))
    get_code_callback = (auth.browser.get_code
                         if options.auth_browser else auth.console.get_code)
    return auth.get_resource(client_secrets, credentials,
                             get_code_callback=get_code_callback)

def get_some_unprocessed_videos(youtube):
    """Try to retrieve some unprocessed videos.
    
    Returns a list of (video_id, title, playlist_item_id) tuples.
    EDIT: {'id': video_id, 'title': video_title, 'desc': video_description, 'itemId': playlist_item_id} dict
    
    Because of the Youtube API quota. We need to limit to process up to N videos
    a day. N is set by flag (default = 10)
    """
    request = youtube.playlistItems().list(
        part='snippet,contentDetails',
        maxResults=UNPROCESSED_LIMIT,
        pageToken=NEXT_PAGE_TOKEN,
        playlistId=unprocessed_playlist
    )
    pl_items_list = request.execute()
    ret = list()
    for item in pl_items_list['items']:
        ret.append(
            {
                'id': item['contentDetails']['videoId'],
                'title': item['snippet']['title'],
                'desc': item['snippet']['description'],
                'itemId': item['id']
            }
        )
    # print(json.dumps(pl_items_list, indent=4))
    if "nextPageToken" in pl_items_list:
        log("NEXT Page Token: " + pl_items_list["nextPageToken"])
    print(json.dumps(pl_items_list["pageInfo"], indent=4))
    return ret

def process_video(video, meeting, youtube):
    """Take a video, which is a (video_id, title, playlist_item_id) tuple.
    Extracts the canonical zoom account from title.
    Extracts GMT date time from title. EDIT: GMT date from meetingdb, meeting is pre-input
    Try to match to a meeting.
    If the meeting has not an associated video, call Youtube API to update the title and description
    of this video.
    Add the video into its destination playlist.
    Remove this video from the unprocessed playlist by the given playlist_item_id.
    Set the video_id back to the meetingsDB.
    """
    can_zid = video['title'].split(' ')[0]  # better to get it from meeting object
    recording_start = meeting.startTime
    # new_title = meeting.className + ' ' + meeting.teacherName + ' ' + str(recording_start)
    new_title = meeting.title
    if "gallery" in video['title']:
        new_title = new_title + " Gallery"

    new_desc = meeting.description + '\n\n###' + can_zid + '|' + meeting.classId + '|' + str(recording_start) + '|' + meeting.teacherName + '|' + meeting.className + '###\n###YJv1###\n' + video['title']
    request = youtube.videos().update(
        part='snippet',
        body={
            'id': video['id'],
            'snippet': {
                'description': new_desc,
                'title': new_title,
                'categoryId': 22
            }
        }
    )
    request.execute()
    log("Updated video %s %s" % (video['id'], new_title))

    request = youtube.playlistItems().insert(
        part='snippet',
        body={
            'snippet': {
                'playlistId': meeting.playlist,
                'resourceId': {
                'kind': 'youtube#video',
                'videoId': video['id']
                }
            }
        }
    )
    request.execute()
    log("Add video %s %s into playlist %s" % (video['id'], new_title, meeting.playlist))

    request = youtube.playlistItems().delete(id=video['itemId'])
    request.execute()
    log("Removed video %s from unprocessed playlist" % video['id'])

def process_unmatched_video(youtube, video):
    new_desc = '''###YJv1:video does not match any meeting###\n%s''' % (video['desc'])
    request = youtube.videos().update(
        part='snippet',
        body={
            'id': video['id'],
            'snippet': {
                'title': video['title'],
                'description': new_desc,
                'categoryId': 22
            }
        }
    )
    request.execute()
    log('Updated unmatched video %s description' % video["id"])
    request = youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": error_processing_playlist,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video['id']
                }
            }
        }
    )
    request.execute()
    log('Added video %s to error processing playlist' % video['id'])
    request = youtube.playlistItems().delete(id=video['itemId'])
    request.execute()
    log('Removed video %s from unprocessed playlist' % video['id'])

def make_playlist(youtube, tlclass):
    title = tlclass.className + ' | ' + tlclass.teacherName
    desc = """###YJv1:%s:%s###""" % (tlclass.classId, tlclass.className)

    request = youtube.playlists().insert(
        part='snippet,status',
        body={
            'snippet': {
                'title': title,
                'description': desc,
                'tags': [],
                'defaultLanguage': 'en'
            },
            'status': {
                'privacyStatus': 'unlisted'
            }
        }
    )
    response = request.execute()
    log("Created a new playlist %s : %s" % (response['id'], title))
    return response['id']

def dry_run(youtube, playlistDB, meetingDB, minutesAllow=15):
    unprocessed_videos = get_some_unprocessed_videos(youtube)

    count_matched = 0
    count_valid = 0
    for video in unprocessed_videos:
        meeting = meetingDB.match(video['title'], minutesAllow)
        if meeting:
            count_matched += 1
            playlist = playlistDB.getPlaylistId(meeting.classId)
            if playlist:
                count_valid += 1
                print('Match with Playlist: %s %s %s' % (video['title'], video['id'], meeting.classId))
            else:
                print('Match without Playlist: %s %s %s' % (video['title'], video['id'], meeting.classId))
        else:
            print('NOT FOUND: %s %s' % (video['title'], video['id']))

    print("%d matched out of %d unprocessed" % (count_matched, len(unprocessed_videos)))
    print("%d videos are eligible for processing" % count_valid)


def run_main(parser, options, args, output=sys.stdout):
    """Run the main scripts from the parsed options/args."""
    youtube = get_youtube_handler(options)
    if not youtube:
        raise AuthenticationError("Cannot get youtube resource")

    playlist_csv_file = options.playlist_json or 'data/playlists.csv'
    playlistDB = classes.PlaylistDB(playlist_csv_file)
    meeting_json_file = options.meeting_json or 'data/meetings.json'
    meetingDB = classes.MeetingDB(meeting_json_file, playlistDB)
    processedCSV = options.processed_csv or 'data/processed.csv'

    if not options.dry_run_off:
        dry_run(youtube, playlistDB, meetingDB)
        return

    # call thinkland module to load the meetingDB object
    # meetingDB = None  # placeholder
    # playlistManager = None
    
    unprocessed_videos = get_some_unprocessed_videos(youtube)
    youtube_points = 1
    v_processed = 0
    skip_processed = 0

    for video in unprocessed_videos:
        meeting = meetingDB.match(video['title'], 20)
        if meeting is None:
            log("Meeting not found: " + video['title'])            
            # TODO: update the video descrition, and move to a ErrorProcessing playlist
            # process_unmatched_video(youtube, video)
            # youtube_points += 160
            # if youtube_points > DAILY_THRESHOLD:
            #     print('Videos processed: ' + str(v_processed))
            #     print('Error processed: ' + str(error_processed))
            #     print("Reached daily youtube points threshold: %d" % youtube_points)
            #     break
            skip_processed += 1
            continue

        # if meeting.playlist is None:
        meeting.playlist = playlistDB.getPlaylistId(meeting.classId)
        if meeting.playlist is None:
            log("Playlist not created yet: " + video['title'])
            continue
        #     meeting.playlist = make_playlist(youtube, meeting)
        #     youtube_points += 50
        #     playlistDB.updatePlaylistId(meeting, meeting.playlist)
        #     playlistDB.writeBack()
        
        process_video(video, meeting, youtube)
        if not meeting.youtubeURL:
            meeting.youtubeURL = f'https://youtube.com/watch?v={video["id"]}'
        else:
            meeting.youtubeURL = meeting.youtubeURL + f'https://youtube.com/watch?v={video["id"]}'
        v_processed += 1
        youtube_points += 160
        if youtube_points > DAILY_THRESHOLD:
            print('Videos processed: ' + str(v_processed))
            print('Skip processed: ' + str(skip_processed))
            print("Reached daily youtube points threshold: %d" % youtube_points)
            break
        # TODO: write processed video file
        appendProcessedVideo(processedCSV, meeting=meeting, videoId=video["id"])


    # meetingDB.writeBack()
    print('Videos processed: ' + str(v_processed))
    print('Skip processed: ' + str(skip_processed))
    print('Used daily youtube points: %d' % youtube_points)


def main(arguments):
    usage = """TODO(jackwaashere): Add usage"""
    parser = optparse.OptionParser(usage)

    # Authentication
    parser.add_option('', '--client-secrets', dest='client_secrets',
                      type="string", help='Client secrets JSON file')
    parser.add_option('', '--credentials-file', dest='credentials_file',
                      type="string", help='Credentials JSON file')
    parser.add_option('', '--auth-browser', dest='auth_browser', action='store_true',
                      help='Open a GUI browser to authenticate if required')

    # Business specific flags
    parser.add_option('', '--meeting_json', dest='meeting_json',
                      type="string", help='path to the json file of meetingDB')
    parser.add_option('', '--playlist_json', dest = 'playlist_json',
                      type='string', help='path to the json file of playlistDB')
    parser.add_option('', '--processed_csv', dest='processed_csv',
                      type='string', help='path to the csv file for processed vidoes')
    parser.add_option('', '--dry_run_off', dest='dry_run_off', action='store_true',
                      help='Turns off dry run mode')

    options, args = parser.parse_args(arguments)

    try:
        run_main(parser, options, args)
    except googleapiclient.errors.HttpError as error:
        response = bytes.decode(error.content).strip()
        raise RequestError(u"Server response: {0}".format(response))


if __name__ == '__main__':
    main(sys.argv[1:])
