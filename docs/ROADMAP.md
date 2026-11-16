# Roadmap

What Grok Bot Twin does today is in the [README](../README.md). This is what comes next, in order. Nothing
here is built yet.

1. **Skills a twin learned on any computer, on all of them.** Today a twin's skills go one way, from the Mac
   with the Grok app to your linked computers, once you switch that on. Next: a skill a twin picked up on a
   linked computer goes back too, so a twin that learned something on one computer knows it on the others.
   Same rule as now: you see what will be copied before it is.

2. **Your chats on all your own computers.** Start a chat on one computer, carry on at another. Chat history
   is end-to-end encrypted between your computers: the computer that passes it along cannot read it.

3. **Files through your cloud storage.** When a twin on another computer needs a file, it goes through a
   cloud-storage connector you have set up, with that service's own sharing rules, not by copying files
   directly between computers.

4. **Sharing a twin with someone else.** Give a colleague or a family member a copy of a twin: its
   instructions and skills, never your chats, your files or your sign-ins. They can stop the sharing at any
   time, and so can you.

**For the one prompt:** a bot-driven twin follows a rename or a new description in Grok by itself (read from
the Grok bot list), a command to put a one-prompt snapshot back, and the local connector route
(`hermes twin mcp`) once the Grok app runs connectors on your computer.

**Two more ways in, designed but not built:** Hermes doing the clicks in the Grok app for you while you watch
and approve each one, and a Grok bot setting itself up as the sync bot
([design/SETUP-ORIGINS.md](design/SETUP-ORIGINS.md)).

Smaller things on the list: choosing which of your computers may ask which ("only my Mac may ask this one"),
a note in the chat when a waiting step has been answered, and a direct path between two linked computers so
the Mac with the Grok app need not be on.
