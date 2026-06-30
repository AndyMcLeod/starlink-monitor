# From Conversation to Telemetry: A Second Case Study in Domain-Expert-Driven Code Generation, and a Test of the Domain-Expert Specification Schema

**Author:** A. McLeod
**Development assistant:** Claude (Anthropic), Claude Code
**Artifact:** `starlink-monitor` - <https://github.com/amcleodUNH/starlink-monitor>

---

## Abstract

This is a second case study. I built a working tool by directing a coding agent. The first case proposed a pattern; this one tests it. The tool is a Python desktop dashboard. It monitors a Starlink dish over the dish's local gRPC interface. It shows live link metrics, a satellite sky map, GPS, on-disk logging, and a firmware guard. I specified it in plain language. I wrote none of the source. I am a marine instrumentation engineer, not a programmer. The hard part is one class of fact, and it is sharper than a mislabeled protocol. The dish answers an undocumented gRPC API. Its field numbers are shifted from the community spec. Worse, several readings are misleading. A buffer looks like signal-to-noise but is not. A number reads like an obstruction score but tracks something else. A panel looks live but is frozen. None of this could be specified up front, because nobody knew it. Each was settled by decoding the bytes and checking against ground truth. I again read the transcript as data and classify the turns. Then I do what the first paper could not. I take the Domain-Expert Specification (DES) schema and test it on a different device, a different protocol, and a much larger artifact. Six of its seven slots transfer cleanly. The one seam is a data-handling concern the schema does not name. I again bound the effort. Active work took a few hours. A three-point estimate for an unaided professional is near 40 person-hours. For a non-programmer alone it is a different regime. This is one case, observed and not controlled. The schema stays a hypothesis, now with a second data point.

**Keywords:** code generation, large language models, human-AI interaction, requirements specification, reverse engineering, protocol discovery, gRPC, satellite communications, end-user programming.

---

## 1. Introduction

The first paper described a practitioner specifying an operational tool in plain language. An agent built it, debugged it, hardened it, and published it. The paper ended with a proposal, not a result. The proposal was a seven-slot prompting schema, the Domain-Expert Specification. It is a hypothesis: people who know their gear but not their compiler might reach a correct artifact in fewer passes. One supporting case is a story, not a finding. This paper adds a second case. I chose it to differ in nearly every dimension that matters. A different device. A protocol that is documented but wrong, not merely hidden. An artifact perhaps three times the size. The question is whether the same division of labor and the same schema hold up.

The setting is marine. A Starlink terminal is now the default over-the-horizon link on a working vessel or an uncrewed surface vehicle. When the link degrades at sea, you want to know why, locally, without an account login. I asked for a tool that watches the dish on the local network and shows me what it is doing. It came back over roughly two dozen turns across two sessions. It is a published desktop application. It has a live link view, a moving map of the satellites overhead, a GPS feed, and telemetry logging. It also has a guard that warns me when the dish updates its own firmware. My aims are the two from before. Record the artifact honestly, including the hard part. Then read the transcript against the schema and see what survives a second case.

---

## 2. The dish, and the telemetry it does not document

A Starlink terminal exposes a gRPC service on its local gateway. The address is `192.168.100.1`, port `9200`. There is no authentication. That much is community knowledge. The trap has two layers.

The first layer is ordinary reverse engineering. The service is undocumented. The field numbers community tools once used no longer match. In this firmware the telemetry fields sit about a thousand higher than the legacy spec. They are not stable across firmware. So the agent rebuilt the schema from the wire. It compiled a protobuf at runtime, called the status and history methods, and walked the raw bytes until each reading matched something physical. This is tedious but mechanical. Off-the-shelf field maps do not survive a firmware bump. A decoder does.

The second layer is the real lesson. It is worse than a hidden protocol. Several readings are not hidden at all. They are present, plausible, and wrong. You catch them only by watching over time or against an independent truth.

- A packed history buffer decodes as believable floats. The obvious reading is "SNR history." It is not. The live SNR the dish streams holds near 16 to 20 dB. The buffer ran 16 to 89, with a mean near 32. An SNR of 89 dB is not a thing. Seeding the SNR chart from it showed fiction.
- A field decodes as a tidy number between 0 and 1. That is where an "obstruction score" belongs. Reported as one, it made no sense. It read high under a clear sky. It swung from 0.62 to 0.44 between polls seconds apart. Real obstruction does not do that. The field is an alignment metric. The boolean that should carry obstruction is itself unreliable here.
- A ten-value array looked like a live per-sector signal map. It never moved. Eight polls in fourteen seconds returned identical values, while throughput and SNR changed normally. It is a slow sky scan that shifts over hours, not a per-second reading. The fix was to relabel it.

You find a hidden protocol by trying harder. You catch a lying reading only by distrusting it. I could not have told the agent any of this up front. I did not know it. The published field maps did not either. It had to be discovered by probing the box and refusing the first plausible answer. That kind of discovery is a capability no wording on my end can supply.

---

## 3. The artifact

The result is a single Python file, `starlink_dashboard.py`. It runs on the standard library plus the gRPC runtime. Two optional packages, `sgp4` and `numpy`, drive the satellite features and are skipped when absent. One file keeps deployment on a vessel's console simple.

A client layer speaks the dish's gRPC dialect. It compiles the embedded protobuf at runtime, so a field map is a one-line edit and a relaunch. It polls status every two seconds on a background thread. It marshals results to the interface safely. A main window shows the live link: download, upload, latency, packet loss, and SNR, each with a sparkline. It also shows a twenty-minute throughput history with a hundred-sample mean, a status panel, and a location panel. The location panel pairs an IP-derived ground-station estimate with the dish's GPS position, the distance between them, and a live scroll of the raw NMEA sentences. A detail window adds a satellite sky map. The map is top-down and dish-centered, drawn with real coastlines and borders. Every Starlink satellite's ground point is propagated with SGP4, so the field moves. The likely satellite is highlighted. The map has a fixed scale, a range ring, and a north indicator (Figure 1). Below it sit a per-sector map, a plain-language readout of the subsystem-ready flags, dish information with firmware and tilt, and extended info. Every poll appends to a daily CSV. The CSV is schema-versioned, so a new column never corrupts a day's file. A firmware check compares the dish's reported build against the verified one. On a mismatch it turns the panel amber and warns, but keeps running. It earned that in §4.

![Figure 1. The detail window: the satellite sky map, with the per-sector map, ready-states, dish info, and extended info.](screenshot-detail.png)

*Figure 1. The detail window, with the dish-centered satellite sky map at top.*

---

## 4. The interaction as method

The tool came together over roughly two dozen turns across two sessions. Table 1 condenses the significant ones. It labels each by function, using the first paper's taxonomy: specification, authorization, defect report, feature, packaging, deferral, context, and constraint. Small layout and packaging turns are folded into the rows. The full transcript is longer than the table.

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

**Turn 11, a knowledge defect surfaced by distrust.** I reported that the SNR chart "appeared to lock up." Later I reported that the obstruction score "makes no sense" against a clear sky. Neither report was clever. Neither needed to be. The screen disagreed with the weather and with the live number beside it. The agent went back to the wire. It set the buffered series next to the streamed SNR. It polled the obstruction field and watched it swing. It found both fields had been mismapped by the spec it inherited. This is the analog of the first project's hidden Modbus dialect. It is irreducible in the same way: it rode on runtime evidence nobody had. I supplied the suspicion, not the answer. The suspicion is what a domain expert carries.

**Turn 14, reliability the field then exercised for real.** I asked for a firmware check. Compare the dish's build to the verified one, warn on a mismatch, keep running. It was a sensible guard against a hypothetical. Days later the dish updated itself over the air. The guard turned the firmware line amber and kept running. The readings still agreed with reality. We promoted the new build to "known." The requirement came from the destination, not a present bug. A dish in the field updates on its own schedule. A tool that trusts stale field numbers will lie the day it does.

**Turn 7, a specification that hit a wall the agent diagnosed.** Mid-project, I asked to rebuild against Starlink's V2 service-account API. I handed over a client id and secret. The agent authenticated. It found the token scoped to the consumer tier, with no access to the telemetry endpoints. "Recode against the cloud API" became "you cannot, with this credential." The agent found the dead end by trying, not guessing. It also kept the secret out of the source and the public repository, and flagged that it should be rotated.

---

## 5. Reading the inputs: what could have been said sooner

Which turns were latent in my first intent? Which were genuinely irreducible?

**The irreducible ones.** Turn 1, the seed, and turn 18, this paper, are required by definition. Turn 11's discovery could only surface once the artifact ran and was watched against ground truth. The same holds for the protocol work behind turn 1 and the wrong-tier credential in turn 7. These are discovery. Discovery is the agent's to do.

**The avoidable ones.** Several turns named something already in my intent. The GPS source and feed (turns 2, 12). The satellite map (turns 9, 16). Publishing and the knowledge bundle (turns 5, 17). The firmware guard (turn 14). Each was said only once its absence was in front of me. The firmware guard is the clearest case. A dish in the field updates itself. A tool keyed to firmware-specific field numbers must notice when the firmware changes. That is a requirement I could have stated on day one.

**A single-pass reconstruction.** Fold the realized intent back into the seed. Set aside the irreducible discovery. You get a request that could have produced most of the final artifact in far fewer passes:

> *Build a standalone, publishable desktop tool to monitor a Starlink dish over its local gRPC interface at 192.168.100.1, for use on a vessel or an uncrewed surface vehicle. I am not a programmer; deliver a single self-contained program I can run with minimal setup. Show the live link - throughput, latency, loss, SNR - with short histories, the dish's pointing and obstruction state, its GPS position from a serial NMEA receiver with the raw feed visible, and a map of the satellites overhead from public orbital elements, with the likely connected satellite highlighted. Log everything to disk. The dish is undocumented and updates its own firmware in the field, so determine the telemetry field numbers empirically rather than trusting any published map, distrust any reading that disagrees with physical reality, and warn me, without stopping, when the firmware changes out from under those mappings. Treat any credential or value I supply as sensitive and keep it out of the published repository. Package it as its own public GitHub repository with a README, an open-source license, and screenshots.*

I do not offer this as a reproach. Discovering your own requirements as you go is normal, and often efficient. A few of these I could not have judged before an artifact made the trade-off concrete. I offer it as evidence. A sizable share of the turns were latent in the first intent. They could have moved to the front.

---

## 6. The Domain-Expert Specification schema, applied to a second case

The first paper proposed the DES schema and could only argue it would help. Here I apply it after the fact to a different project. I grade each of its seven slots.

1. **Device and interface.** A Starlink dish, reached over Ethernet at `192.168.100.1`, speaking gRPC. *Fits. Naming the address and transport pointed the agent at the right surface. It bounded the protocol hunt from the first line.*
2. **Operational repertoire.** Watch the link metrics, pointing and obstruction, GPS, and the satellites overhead. Log it. Survive a firmware change. *Fits. It is again the slot I under-filled; the map and the logging were latent. It is also the slot I am best placed to fill. It is just the watch I want written down.*
3. **Field context and deployment.** A vessel or USV. An over-the-horizon link that matters operationally and degrades without warning. *Fits, and it does real work. "The dish updates itself in the field" licenses the firmware guard.*
4. **Authorization and safety envelope.** Here is the strain. In the first project this meant "you may switch the relays, nothing is connected." Here the dish is live and read-only. There was nothing to authorize, so the slot fell idle. *It mostly does not apply to a read-only instrument. The safety concern that did matter was my data. Slot 4 does not name that.*
5. **Deferred parameters.** The verified firmware build, and earlier the GPS port. *Fits. I named the firmware build as a verified-against constant, not a hard assumption. That made the guard possible instead of a silent breakage.*
6. **Deliverable and distribution.** A single runnable program in its own public, documented repository, released and packaged. *Fits. Stating it first would have collapsed several packaging turns into the opening pass.*
7. **Verification expectation.** Verify against reality: the streamed value, the clear sky, the same field one poll later. Verify against an independent model where ground truth is thin. *Fits, and it earned the most here. The satellite math was checked against an independent ephemeris library to a fraction of a degree. The mismapped fields were caught by holding a reading against a streamed truth. This slot is the whole game when the device's own readings cannot be trusted.*

Six of seven slots transfer to a very different project unchanged. The schema's core refusal held. I specified no field numbers, no projection math, no threading model. Those are exactly the parts that had to be discovered or engineered. The seam is slot 4. On a read-only instrument the device-authorization framing goes slack. A different concern took its place: handling a credential I pasted into the conversation. That is not what slot 4 was built to capture. The agent handled it correctly on its own. The schema did not prompt me to state it. From one case I will not add an eighth slot. But the point stands. When a domain expert hands an agent anything sensitive, there is a data-handling expectation. It belongs in the specification. Slot 4 should read as "what is the safety envelope, for the device and for my data both."

---

## 7. How long it took, and how long it might otherwise have taken

I treat duration as effort in person-hours, not calendar time. The wall-clock span ran across two sessions over several days. Most of that was idle. I was waiting on my availability, my review, and the dish dropping off the network and coming back.

### 7.1 Method

For the AI-coupled side I bound active effort from the record. The work ran across roughly two dozen short turns and bounded replies. Version-control timestamps land minutes apart. A string of releases marks the larger steps. This project was bigger than the first and ran longer. It had more iteration and a great deal of live verification. Active effort, meaning agent generation plus my reading and direction, comes to a few hours. Call it three to four. I report it as an order-of-magnitude figure and round up. I would rather overstate the human-review cost than understate it.

For the unaided side there is nothing to measure. So I estimate it. I break the artifact into nine components. I give each a three-point estimate: optimistic *a*, most-likely *m*, pessimistic *b*. I apply the PERT approximation: *t*ₑ = (*a* + 4*m* + *b*)/6, and *σ* = (*b* − *a*)/6. The components are independent, so the total variance is the sum. The baseline assumes a competent professional. That is generous, since the person who directed the work calls himself a non-programmer. Scope matches what was delivered. Discovery, the satellite and mapping work, verification, reliability, and packaging are all in.

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

The components total 40.3 person-hours, with a standard deviation of 4.3 h. The total *σ* is the root-sum-square of the components. A normal approximation puts a 90% interval at roughly 33 to 47 hours. That is about a working week. The largest and shakiest lines are the discovery-heavy ones. An unaided developer has no quick probe-decode-and-distrust loop. They must work out alone that the field numbers moved. Harder still, they must work out that several plausible readings lie.

### 7.3 Comparison

Against that baseline, the AI-coupled work produced a tested, published, multi-release artifact in a few hours. That is an order-of-magnitude reduction. It is a smaller multiple than the first project's, and honestly so. This artifact is larger. More of its bulk is ordinary interface and mapping code, which a professional writes briskly. The comparison against my actual alternative is sharper for being unquantifiable. I am not a developer. Building this unaided does not start at 40 hours. It starts with acquiring gRPC, protobuf, orbital mechanics, serial parsing, threading, and desktop UI. Only then does the real work begin. The honest outcomes are some large multiple of the estimate, or non-completion. For someone like me the comparison is not "a few hours versus forty." It is a working tool versus none.

### 7.4 Threats to validity

The AI-coupled figure is an uninstrumented order-of-magnitude bound. The unaided figure is a modeled estimate, not a measurement. Three-point estimates drift with the estimator's anchor. Both rest on n = 1. They sit beside a second n = 1, not aggregated with it. The professional baseline could run either way. It depends on how much gRPC and orbital work the developer already brings. I widened the pessimistic discovery bounds to absorb some of that. The ratio from one small instrument should not stretch to large systems. There, architecture and maintenance dominate. These figures describe single-purpose field instrumentation, and not much beyond.

---

## 8. Discussion

The division of labor held. The second case strengthens it. The practitioner brings the what and the why: the device, the watch I want to stand, where it is going, what "done" looks like, and the suspicion that a reading is wrong. The agent brings the how: protocol framing, orbital math, interface, and threading. The agent also brings discovery, the facts you can only learn at runtime. That includes the uncomfortable facts, where the telemetry misleads. No specification could have prevented the key corrections. The moved field numbers. The two mismapped readings. The frozen sky-scan array. The wrong-tier credential. All fell on the agent's side of the line. That is where the schema's refusal to ask users for implementation would put them.

The second case adds a test, not another argument. It came back mostly positive, with one named seam. Six of seven slots transferred unchanged. The verification slot did heavy lifting, because this device's readings could not be taken at face value. The seam was slot 4. Device-authorization went idle on a read-only instrument. A data-handling concern took its place. The agent handled it well, unprompted. The schema did not prompt me to state it.

The caveats from the first paper still apply. One is sharper. This is again n = 1, with no control. The user-and-agent pair is not one I can call representative. Some apparent under-specification is good practice. I could not have judged the firmware guard's exact behavior before watching the field numbers' fragility. I could have named the requirement, though. The schema also leans hard on a capable agent. It needs one that can do empirical discovery and distrust its own first reading. Against a weaker system, slots 4 and 7 give back much less.

Future work is the head-to-head I called for before. Now it has two grounding cases. Run paired tasks, with and without the structured prompt, across several domain users and devices. Measure turns to acceptance, defect counts, and instrumented time against matched unaided controls. Measure the share of corrections that trace to specification gaps versus discovery.

---

## 9. Conclusion

A field practitioner produced, debugged, hardened, and published a second operational device-monitoring application by conversation alone. The work leaned on domain knowledge, not programming skill. This time the device's telemetry was not merely undocumented. In places it was actively misleading. The interaction compressed effort by roughly an order of magnitude against an estimated professional baseline. For a non-programmer, it again plausibly made the difference between a working tool and none. About half the turns supplied requirements latent in the original intent. Those could have been hoisted into a single pass. The irreducible minority were discovery, and properly the agent's to carry. Most usefully, I could finally test the DES schema, not just propose it. Six of its seven slots transferred to a markedly different project. The one seam, a safety envelope for my data, is named for the next revision. Two cases are not a validation. They are a second data point pointing the same direction as the first. That is reason enough to keep asking the question with proper controls. And to keep handing the discovery to the side that can actually do it.

---

### Materials and reproducibility

The complete artifact lives at <https://github.com/amcleodUNH/starlink-monitor> under the MIT License, across tagged releases. It includes the runtime-compiled gRPC client, the two-window interface, and the satellite sky map. The telemetry field mappings were established by wire-decoding the dish's own replies. They were verified against the firmware build named in the application's `KNOWN_FIRMWARE` constant. The satellite look-angle math was cross-checked against an independent ephemeris library, to within a fraction of a degree. The mismapped fields of §2 were identified by holding a decoded reading against a streamed value, a clear sky, or the same field on a later poll.

### A note on authorship

The software artifact and a draft of this paper were generated by an LLM coding agent (Claude, Anthropic), under the direction of the human author. His inputs were the specification; §4 and §5 reproduce and analyze them. Most of the typing was not mine. The paper reads those inputs back, and grades a schema the author co-proposed. Take that provenance into account.
