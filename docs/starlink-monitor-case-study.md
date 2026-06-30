# From Conversation to Telemetry: A Second Case Study in Domain-Expert-Driven Code Generation, and a Test of the Domain-Expert Specification Schema

**Author:** A. McLeod
**Development assistant:** Claude (Anthropic), Claude Code
**Artifact:** `starlink-monitor` - <https://github.com/amcleodUNH/starlink-monitor>

---

## Abstract

This is a second case study in building a working tool by directing a coding agent, and a chance to test a pattern proposed in the first. The artifact is a standalone Python desktop dashboard that monitors a Starlink dish over its local gRPC interface, with live link metrics, a satellite sky map, GPS, on-disk logging, and a firmware guard; as before, I specified it in plain language and wrote none of the source. I am a marine instrumentation engineer, not a programmer. The hard part is again a single class of non-obvious fact, sharper here than a mislabeled protocol: the dish answers an undocumented gRPC API whose field numbers are shifted from the community spec and, worse, several readings are actively misleading - a buffer that looks like signal-to-noise but is not, a number that reads like an obstruction score but tracks something else, a panel that looks live but is frozen. None of it could be specified up front because none of it was known; each was settled only by wire-decoding the bytes and checking against ground truth. I again read the transcript as data, classify the turns, and then do what the first paper could only propose: I take the Domain-Expert Specification (DES) schema and ask whether it fits a different device, protocol, and a far larger artifact. Six of its seven slots transfer cleanly; the one seam is a data-handling concern the schema does not name. I again bound effort - a few hours of active attention against a three-point estimate near 40 person-hours for an unaided professional, and a different regime entirely for a non-programmer alone. One case again, observed and not controlled; the schema remains a hypothesis, now with a second data point.

**Keywords:** code generation, large language models, human-AI interaction, requirements specification, reverse engineering, protocol discovery, gRPC, satellite communications, end-user programming.

---

## 1. Introduction

The first paper in this series described a practitioner specifying an operational tool in plain language and an agent building, debugging, hardening, and publishing it. It ended with a proposal rather than a result: a seven-slot prompting schema, the Domain-Expert Specification, offered as a hypothesis about how people who know their gear but not their compiler might reach a correct artifact in fewer passes. A hypothesis with one supporting case is a story, not a finding. This paper adds a second case, chosen to differ in nearly every dimension that matters - a different device, a protocol that is documented but wrong rather than merely hidden, and an artifact perhaps three times the size - and asks whether the same division of labor and the same schema hold up.

The setting is marine. A Starlink terminal is now the default over-the-horizon link on a working vessel or an uncrewed surface vehicle, and when the link degrades at sea you want to know why, locally, without an account login. I asked for a tool that watches the dish on the local network and shows me what it is doing. What came back, over roughly two dozen turns across two sessions, was a published desktop application with a live link view, a moving map of the satellites overhead, a GPS feed, telemetry logging, and a guard that warns me when the dish updates its own firmware out from under the field mappings the tool depends on. My aims are the two from before: record the artifact honestly, including the part that was genuinely hard, then read the transcript against the schema the last paper proposed and see what survives a second case.

---

## 2. The dish, and the telemetry it does not document

A Starlink terminal exposes a gRPC service on its local gateway, `192.168.100.1`, port `9200`, with no authentication. That much is community knowledge. The trap has two layers.

The first is ordinary reverse engineering. The service is undocumented, and the field numbers community tools once relied on no longer match: in this firmware the telemetry fields sit roughly a thousand higher than the legacy spec, and they are not stable across firmware. So the agent rebuilt the schema from the wire - compiling a protobuf at runtime, calling the status and history methods, and walking the raw bytes until each reading lined up with something physical. Tedious but mechanical; off-the-shelf field maps do not survive a firmware bump, but a decoder does.

The second layer is the real lesson, and it is worse than a hidden protocol: several readings are not hidden at all, but present, plausible, and wrong, exposed only by watching them over time or against an independent truth.

- A packed history buffer decodes as believable floats, and the obvious reading is "SNR history." It is not: against the live SNR the dish streams (steady near 16 to 20 dB), the buffer ran 16 to 89 with a mean near 32, and an SNR of 89 dB is not a thing. Seeding the SNR chart from it was showing fiction.
- A field decodes as a tidy number between 0 and 1, exactly where an "obstruction score" belongs. Reported as one it made no sense: it read high under a provably clear sky and swung from 0.62 to 0.44 between polls seconds apart. Real obstruction does not do that; the field is an alignment metric, and the boolean that ought to carry obstruction is itself unreliable on this firmware.
- A ten-value array looked like a live per-sector signal map but never moved - byte-for-byte identical across eight polls in fourteen seconds while throughput and SNR changed normally. It is a slowly-accumulated sky scan that shifts over hours, not a per-second reading; the fix was relabeling it as what it is.

A hidden protocol you find by trying harder; a reading that lies you catch only by distrusting it, setting it beside a streamed value or a clear sky and watching for the contradiction. I could not have told the agent any of this up front: I did not know it, and the published field maps did not either. It had to be discovered by probing the box and refusing the first plausible answer, and that kind of discovery is a capability no wording on my end can supply.

---

## 3. The artifact

The result is a single Python file, `starlink_dashboard.py`, that runs on the standard library plus the gRPC runtime, with two optional packages (`sgp4`, `numpy`) used only by the satellite features and skipped gracefully when absent. One file keeps deployment on a vessel's console painless.

A client layer speaks the dish's gRPC dialect: it compiles the embedded protobuf at runtime (no build step, so a field map is a one-line edit and a relaunch), polls status every two seconds on a background thread, and marshals results to the interface safely. A main window shows the live link - download and upload, latency, packet loss, SNR, each with a sparkline - a twenty-minute throughput history with a hundred-sample mean, a status panel, and a location panel pairing an IP-derived ground-station estimate with the dish's GPS position, the distance between them, and a live scroll of the raw NMEA sentences. A detail window adds a satellite sky map: a top-down, dish-centered map drawn with real coastlines and borders, every Starlink satellite's ground point propagated with SGP4 so the field moves, the likely satellite highlighted, a fixed scale, a range ring, and a north indicator (Figure 1). Below it sit a per-sector map, a plain-language readout of the subsystem-ready flags, dish information including firmware and tilt, and extended info. Every poll appends to a daily CSV, schema-versioned so a new column never corrupts a day's file. A firmware check compares the dish's reported build against the one the mappings were verified on, turning the panel amber with a warning on a mismatch while continuing to run - which it earned in §4.

![Figure 1. The detail window: the satellite sky map, with the per-sector map, ready-states, dish info, and extended info.](screenshot-detail.png)

*Figure 1. The detail window, with the dish-centered satellite sky map at top.*

---

## 4. The interaction as method

The tool came together over roughly two dozen turns across two sessions. Table 1 condenses the significant ones and labels each by function, using the first paper's taxonomy: *specification*, *authorization*, *defect report*, *feature*, *packaging*, *deferral*, *context*, and *constraint*. Small layout and packaging turns are folded into the rows; the full transcript is longer than the table.

**Table 1. The development interaction, by turn (condensed).**

| # | User input (condensed) | Function | Elicited |
|---|------------------------|----------|----------|
| 1 | Starlink dish at 192.168.100.1; find the debug interface and build a monitoring dashboard | Specification | Initial system; gRPC API and field-number discovery |
| 2 | Add a COM-port selector for the GPS, default COM10 | Feature | Serial GPS source selection |
| 3 | The "obstructed" value reads true under a 100% clear sky; confirm and correct | Defect report | Discovery: the obstruction boolean is unreliable on this firmware |
| 4 | Are the dish nickname and data-usage values available locally? | Specification (inquiry) | Confirmed server-side only; not in the local API |
| 5 | Make the project portable and publish it to GitHub | Packaging | Repository, README, license, .gitignore |
| 6 | Make values copyable, enlarge fonts, fix obscured sky data, age the obstruction events | Feature + defect | Usability and layout corrections |
| 7 | Recode against the Starlink V2 service-account API (client id and secret supplied) | Specification | Discovery: the credential is consumer-scoped and cannot reach the telemetry API |
| 8 | Abandon that approach; delete the tokens | Constraint | Reverted to the local API; secret handling |
| 9 | Add a "likely satellite" estimate from TLE data | Feature | CelesTrak TLE plus SGP4 look-angle matching |
| 10 | Panel text does not scale and gets masked by other panels; fix within reason | Defect report | Window-scaled fonts; Location panel rebuilt |
| 11 | The buffered SNR is far higher than the streamed value; confirm the right data is used. The obstruction score makes no sense, high under a clear view | Defect report | Discovery: history field is not SNR; signal field is not obstruction |
| 12 | Add a live, scrolling NMEA feed box | Feature | Raw serial sentences on screen |
| 13 | Make the ready-states panel descriptive; the acronyms are not obvious | Feature (usability) | Plain-language subsystem labels |
| 14 | Add a firmware-version check; alert on a mismatch but keep running | Reliability | Firmware guard (later caught a real over-the-air bump) |
| 15 | The per-sector values never change; are they captured once and ignored? Also log them | Defect report + Feature | Discovery: the array is a slow sky-scan map; logged for study |
| 16 | Build a moving sky map from the TLE data around the dish, with a background map, and highlight the likely sat | Feature | Dish-centered satellite map with real borders |
| 17 | Turn the project into a Claude Project; bundle the chats and code | Packaging (meta) | Knowledge bundle; secret redaction |
| 18 | Write this paper | Meta | The present document |

Three turns fall on the line between a defect of specification and one of implementation or knowledge.

**Turn 11, a knowledge defect surfaced by distrust.** I reported that the SNR chart "appeared to lock up" and that the obstruction score "makes no sense" against a clear sky. Neither report was clever, and neither needed to be: the screen disagreed with the weather and with the live number beside it. From those two complaints the agent went back to the wire, set the buffered series next to the streamed SNR, polled the obstruction field and watched it swing, and found both had been mismapped by the spec it inherited. This is the analog of the first project's hidden Modbus dialect, irreducible in the same way - it rode on runtime evidence nobody had. I supplied not the answer but the suspicion, and the suspicion is what a domain expert carries.

**Turn 14, reliability the field then exercised for real.** I asked for a firmware check: compare the dish's build to the verified one, warn on a mismatch, keep running. A sensible guard against a hypothetical. Days later the dish updated itself over the air, the guard turned the firmware line amber and kept running, the readings still agreed with reality, and we promoted the new build to "known." The requirement came from the destination rather than a present bug - a dish in the field updates on its own schedule, and a tool that silently trusts stale field numbers will lie the day it does.

**Turn 7, a specification that hit a wall the agent diagnosed.** I asked, mid-project, to rebuild against Starlink's V2 service-account API, and handed over a client id and secret. The agent authenticated and found the token scoped to the consumer tier, unable to reach the telemetry endpoints; "recode against the cloud API" became "you cannot, with this credential," established empirically, and we reverted. The dead end was found by trying, not guessing - and the agent, unprompted, kept the secret out of the source and the public repository and flagged that it should be rotated.

---

## 5. Reading the inputs: what could have been said sooner

Of the turns in Table 1, which were latent in my first intent and could have been hoisted into the opening pass, and which were genuinely irreducible?

**The irreducible ones.** Turn 1 (the seed) and turn 18 (this paper) are required by definition. Turn 11's discovery could only surface once the artifact ran and was watched against ground truth; the same holds for the protocol work behind turn 1 and the wrong-tier credential in turn 7. These are discovery, and discovery is the agent's to do.

**The avoidable ones.** The GPS source and feed (turns 2, 12), the satellite map (turns 9, 16), publishing and the knowledge bundle (turns 5, 17), and the firmware guard (turn 14) each named something already in my intent but said only once its absence was in front of me. The firmware guard is the clearest: a dish in the field updates itself, so a tool keyed to firmware-specific field numbers must notice when the firmware changes - a non-functional requirement available on day one.

**A single-pass reconstruction.** Fold the realized intent back into the seed and you get a request that, setting aside the irreducible discovery, could have produced substantially the final artifact in far fewer passes:

> *Build a standalone, publishable desktop tool to monitor a Starlink dish over its local gRPC interface at 192.168.100.1, for use on a vessel or an uncrewed surface vehicle. I am not a programmer; deliver a single self-contained program I can run with minimal setup. Show the live link - throughput, latency, loss, SNR - with short histories, the dish's pointing and obstruction state, its GPS position from a serial NMEA receiver with the raw feed visible, and a map of the satellites overhead from public orbital elements, with the likely connected satellite highlighted. Log everything to disk. The dish is undocumented and updates its own firmware in the field, so determine the telemetry field numbers empirically rather than trusting any published map, distrust any reading that disagrees with physical reality, and warn me, without stopping, when the firmware changes out from under those mappings. Treat any credential or value I supply as sensitive and keep it out of the published repository. Package it as its own public GitHub repository with a README, an open-source license, and screenshots.*

I offer this not as a reproach to how the conversation went. Discovering your own requirements as you go is normal and often efficient, and a few of these I could not have judged before an artifact made the trade-off concrete. I offer it as evidence that a sizable share of the turns were latent in the first intent, and so could have been moved to the front.

---

## 6. The Domain-Expert Specification schema, applied to a second case

The first paper proposed the DES schema and could only argue it would help. Here I apply it after the fact to a different project and grade each of its seven slots.

1. **Device and interface.** A Starlink dish, reached over Ethernet at `192.168.100.1`, speaking gRPC. *Fits. Naming the address and transport pointed the agent at the right surface and bounded the protocol hunt from the first line.*
2. **Operational repertoire.** Watch the link metrics, pointing and obstruction, GPS, the satellites overhead; log it; survive a firmware change. *Fits, and again the slot I under-filled - the map and the logging were latent. It is also the one I am best placed to fill, being just the watch I want written down.*
3. **Field context and deployment.** A vessel or USV, an over-the-horizon link that matters operationally and degrades without warning. *Fits, and it does real work: "the dish updates itself in the field" licenses the firmware guard.*
4. **Authorization and safety envelope.** Here is the strain. In the first project this meant "you may switch the relays, nothing is connected"; here the dish is live and read-only, so there was nothing to authorize and the slot fell idle. *Mostly not applicable to a read-only instrument - and the safety concern that did matter was my data, which slot 4 does not name (see below).*
5. **Deferred parameters.** The verified firmware build, and earlier the GPS port. *Fits. Naming the firmware build as a verified-against constant, not a hard assumption, is what made the guard possible instead of a silent breakage.*
6. **Deliverable and distribution.** A single runnable program in its own public, documented repository, released and packaged. *Fits, and stating it first would have collapsed several packaging turns into the opening pass.*
7. **Verification expectation.** Verify against reality - the streamed value, the clear sky, the same field one poll later - and against an independent model where ground truth is thin. *Fits, and it earned the most here: the satellite math was checked against an independent ephemeris library to a fraction of a degree, and the mismapped fields were caught by holding a reading against a streamed truth. This slot is the whole game when the device's own readings cannot be trusted.*

Six of seven slots transfer to a very different project unchanged, more than I expected, and the schema's core refusal held: I specified no field numbers, no projection math, no threading model, which are exactly the parts that had to be discovered or engineered. The seam is slot 4. On a read-only instrument the device-authorization framing goes slack, while a different concern - handling a credential I pasted into the conversation - turned out to matter and is not what slot 4 was built to capture. The agent handled it correctly on its own, but the schema did not prompt me to state it. From one case I will not add an eighth slot; I will note that as soon as a domain expert hands an agent anything sensitive, there is a data-handling expectation that belongs in the specification, and slot 4 should read as "what is the safety envelope, for the device and for my data both."

---

## 7. How long it took, and how long it might otherwise have taken

I treat duration as effort in person-hours, not calendar time. The project's wall-clock span ran across two sessions over several days, but most of that was idle - waiting on my availability, my review, and the dish dropping off the network and coming back.

### 7.1 Method

For the AI-coupled side I bound active effort from the record: roughly two dozen short turns and bounded replies, with version-control timestamps minutes apart and a string of releases marking the larger steps. This project was bigger than the first and ran longer, with more iteration and a great deal of live verification. Active effort - agent generation plus my reading and direction - comes to a few hours, call it three to four. I report it as an order-of-magnitude figure and round up, preferring to overstate the human-review cost than understate it.

For the unaided side there is nothing to measure, so I estimate it. I break the artifact into nine components, give each a three-point estimate (optimistic *a*, most-likely *m*, pessimistic *b*), and apply the PERT approximation: *t*ₑ = (*a* + 4*m* + *b*)/6, *σ* = (*b* − *a*)/6, with independent components so the total variance is the sum. The baseline assumes a competent professional, generous given that the person who directed the work calls himself a non-programmer. Scope matches what was delivered: discovery, the satellite and mapping work, verification, reliability, and packaging are all in.

### 7.2 Result

**Table 2. Three-point (PERT) effort estimate for an unaided professional build.** All values in person-hours.

| Work component | *a* | *m* | *b* | *t*ₑ | *σ* |
|----------------|----:|----:|----:|-----:|----:|
| API and protocol discovery (gRPC, runtime proto, field-number map, catch mismapped fields) | 3.0 | 8.0 | 20.0 | 9.17 | 2.83 |
| gRPC client and embedded runtime-compiled proto | 1.0 | 3.0 | 6.0 | 3.17 | 0.83 |
| Core GUI (cards, sparklines, history, layout, window scaling) | 3.0 | 6.0 | 12.0 | 6.50 | 1.50 |
| GPS (NMEA serial parse, IP geolocation, persistence) | 1.5 | 3.5 | 7.0 | 3.75 | 0.92 |
| Satellite estimate and sky map (SGP4 sub-points, geodetics, vector borders, projection, animation) | 3.0 | 7.0 | 15.0 | 7.67 | 2.00 |
| Data logging and schema-safe rotation | 0.5 | 1.5 | 3.0 | 1.58 | 0.42 |
| Reliability (threading, reconnect, firmware guard) | 1.0 | 2.5 | 6.0 | 2.83 | 0.83 |
| Testing and verification (headless tests, ephemeris cross-check) | 1.0 | 3.0 | 7.0 | 3.33 | 1.00 |
| Packaging and publishing (repo, README, releases, screenshots) | 1.0 | 2.0 | 5.0 | 2.33 | 0.67 |
| **Total** | | | | **40.3** | **4.3** |

The components total 40.3 person-hours with a standard deviation of 4.3 h (the total *σ* is the root-sum-square of the components); a normal approximation puts a 90% interval at roughly 33 to 47 hours, about a working week. The largest and shakiest lines are the discovery-heavy ones: an unaided developer, without a quick probe-decode-and-distrust loop, has to work out alone both that the field numbers moved and, harder, that several plausible readings lie.

### 7.3 Comparison

Against that baseline, the AI-coupled work produced a tested, published, multi-release artifact in a few hours of active effort - an order-of-magnitude reduction, a smaller multiple than the first project's and honestly so, because this artifact is larger and more of its bulk is ordinary interface and mapping code a professional writes briskly. The comparison against my actual alternative is sharper for being unquantifiable: I am not a developer, and building this unaided does not start at 40 hours but with acquiring gRPC, protobuf, orbital mechanics, serial parsing, threading, and desktop UI before the real work begins. Its honest outcomes are some large multiple of the estimate, or non-completion. For someone like me the operative comparison is not "a few hours versus forty"; it is a working tool versus none.

### 7.4 Threats to validity

The AI-coupled figure is an uninstrumented order-of-magnitude bound; the unaided figure is a modeled estimate, not a measurement, and three-point estimates drift with the estimator's anchor. Both rest on n = 1, now beside a second n = 1 rather than aggregated with it. The professional baseline could run either way depending on how much gRPC and orbital work the developer brings; I widened the pessimistic discovery bounds to absorb some of that. And the ratio from one small instrument should not be stretched to large systems, where architecture and maintenance dominate. These figures describe single-purpose field instrumentation, and not much beyond.

---

## 8. Discussion

The division of labor held, and the second case strengthens it. The practitioner brings the *what* and the *why*: the device, the watch I want to stand, where it is going, what "done" looks like, and the suspicion that a reading is wrong. The agent brings the *how* - protocol framing, orbital math, interface, threading - and the *discovery* of facts learnable only at runtime, including the uncomfortable ones where the telemetry misleads. Every correction no specification could have prevented - the moved field numbers, the two mismapped readings, the frozen sky-scan array, the wrong-tier credential - fell on the agent's side of that line, where the schema's refusal to ask users for implementation would put them.

What the second case adds is a test rather than another argument, and it came back mostly positive with one named seam. Six of seven slots transferred unchanged, and the verification slot did heavy lifting precisely because this device's readings could not be taken at face value. The seam was slot 4: device-authorization went idle on a read-only instrument while a data-handling concern I did not anticipate turned out to matter, was handled well by the agent unprompted, and was not something the schema prompted me to state.

The caveats from the first paper still apply, one sharper. This is again n = 1, with no control and a user-and-agent pair I cannot claim is representative. Some apparent under-specification is good practice - I could not have judged the firmware guard's exact behavior before watching the field numbers' fragility, even if I could have named the requirement. And the schema leans hard on an agent that can do empirical discovery and distrust its own first reading; against a weaker system, slots 4 and 7 would give back much less.

Future work is the same head-to-head I called for before, now with two grounding cases: paired tasks with and without the structured prompt, across several domain users and devices, measuring turns to acceptance, defect counts, instrumented time against matched unaided controls, and the share of corrections tracing to specification gaps versus discovery.

---

## 9. Conclusion

A field practitioner produced, debugged, hardened, and published a second operational device-monitoring application by conversation alone, leaning on domain knowledge rather than programming skill - this time against a device whose telemetry is not merely undocumented but, in places, actively misleading. The interaction compressed effort by roughly an order of magnitude against an estimated unaided professional baseline, and for a non-programmer it again plausibly made the difference between a working tool and none. About half the turns supplied requirements latent in the original intent and could have been hoisted into a single pass; the irreducible minority were discovery, and properly the agent's to carry. Most usefully, I could finally test the Domain-Expert Specification schema rather than only propose it, and six of its seven slots transferred to a markedly different project, with the one seam - a safety envelope for my data, not just the device - named for the next revision. Two cases are not a validation. They are a second data point pointing the same direction as the first, which is reason enough to keep asking the question with proper controls, and to keep handing the discovery to the side that can actually do it.

---

### Materials and reproducibility

The complete artifact - the runtime-compiled gRPC client, the two-window interface, the satellite sky map, and the figure reproduced here - lives at <https://github.com/amcleodUNH/starlink-monitor> under the MIT License, across tagged releases. The telemetry field mappings were established by wire-decoding the dish's own replies and verified against the firmware build named in the application's `KNOWN_FIRMWARE` constant; the satellite look-angle math was cross-checked against an independent ephemeris library to within a fraction of a degree, and the mismapped fields of §2 were identified by holding a decoded reading against a streamed value, a clear sky, or the same field on a later poll.

### A note on authorship

The software artifact and a draft of this paper were generated by an LLM coding agent (Claude, Anthropic) under the direction of the human author, whose inputs - reproduced and analyzed in §4 and §5 - were the specification. Most of the typing was not mine. The paper's self-referential reading of those inputs, and its grading of a schema the author co-proposed, should be taken with that provenance in mind.
