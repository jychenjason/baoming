# Event Registration

This context manages one event's invitations, participant responses, and attendance or meal counts.

## Language

**Event**:
An organized occasion that participants can respond to through its private link.
_Avoid_: Activity

**Public link**:
A secret URL that grants access to one event's participant experience and roster after the anti-bot question.
_Avoid_: Invite code

**Option group**:
A question within an event whose participant may choose at most one answer.
_Avoid_: Category

**Attendance**:
A participant's answer stating whether they will attend an event.
_Avoid_: RSVP status

**Registration**:
One participant's response to one event, identified within that event by their normalized name.
_Avoid_: Attendee account

**Registration choice**:
A participant's selected answer for one custom option group.
_Avoid_: Attendance choice

**Roster**:
The event's participant registrations and their visible answers.
_Avoid_: Directory

**Participant**:
A person responding to an event without creating an account.
_Avoid_: User

**Administrator**:
The person who manages events and registrations through the password-protected interface.
_Avoid_: Organizer account
