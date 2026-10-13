# Ask questions

The **Ask** tab sends a question in plain words to an AI agent. The agent answers only from the area's data. It shows the queries
that it used, and it shows the things that its answer is about on the map.

## Set a key

The agent needs an API key on the computer that runs `urbanstyle serve`. Keys stay on that computer and never go into the repository.

- **Claude (Anthropic).** Put the key in `~/.config/anthropic/key`, or set `ANTHROPIC_API_KEY`. Make a key at
  <https://console.anthropic.com>. A Claude subscription does not include API use.

    ```bash
    mkdir -p ~/.config/anthropic && printf '%s' 'sk-ant-...' > ~/.config/anthropic/key && chmod 600 ~/.config/anthropic/key
    ```

- **Gemini (Google).** Set `GEMINI_API_KEY` before you start the server. The agent uses Gemini only when no Anthropic key is set.

The server reads the Anthropic key file at each question, so a new key needs no restart. A change to `GEMINI_API_KEY` needs a
restart of the server.

## Ask

1. Open **Ask**.
2. Type a question, or click one of the examples. For example: "Where are the sidewalks narrower than 1.8 m?"
3. Wait for the answer. It can take a minute: the agent runs several queries.

The answer gives the numbers and their sources. Under the answer, "queries used" shows each SQL query, so that you can check it.
The things that the answer is about show in the list and on the map.

## Ask a follow-up question

The agent remembers the conversation: "And only on Granville Street?" works. The conversation stays after a page reload. To start
again, click **New conversation**.

If the server restarts, it forgets the conversation. The next answer then says so.

## Limits of Gemini's free tier

- The free tier has no Pro model. The agent uses the Flash models first, and the Lite models only when every Flash model is used up.
  In a test, a Lite model gave a wrong source for the sidewalk widths. Check the sources of a Lite answer against the card.
- Each model allows 5 requests a minute and 20 a day. One question uses up to 12 requests. The agent waits when Gemini asks it to,
  and goes on with the next model when one is busy or used up.
- For more questions a day, enable billing on the Google project of the key, or set an Anthropic key.

To choose the first Gemini model, set `URBANSTYLE_GEMINI_MODEL`, for example `gemini-3.7-flash`.
