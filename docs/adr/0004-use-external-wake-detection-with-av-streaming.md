# Use external wake detection with AV streaming

The first version will keep Misty's AV stream active so one external pipeline
can support simultaneous visual attention and configurable `Hey Misty` or
`Hi Misty` detection. Misty's built-in wake phrase and sound-direction modes
remain optional hardware-unverified providers because the vendor documents
their microphone use as incompatible with active AV streaming; switching
providers must not change the Attention Loop or Episode interfaces.

Decoder EOF and failure cross that provider seam as typed terminal outcomes
rather than leaving the Attention Loop polling forever. Hosted ASR retries are
disabled so the configured timeout bounds the one wake-authorised attempt.
