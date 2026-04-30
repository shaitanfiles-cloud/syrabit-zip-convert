# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: pwa-permission.spec.ts >> Push notification permission request — real UI trigger >> granted: clicking "Push Off" calls requestPermission(), gets granted, and POSTs the subscription
- Location: tests/pwa-permission.spec.ts:134:3

# Error details

```
Error: expect(received).not.toBeNull()

Received: null

Call Log:
- Timeout 8000ms exceeded while waiting on the predicate
```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - link "Skip to main content" [ref=e2] [cursor=pointer]:
    - /url: "#main-content"
  - generic [ref=e3]:
    - generic [ref=e4]:
      - complementary [ref=e5]:
        - generic [ref=e7]:
          - img "Syrabit.ai" [ref=e9]
          - generic [ref=e10]:
            - paragraph [ref=e11]: Syrabit.ai
            - paragraph [ref=e12]: Control Center
        - navigation [ref=e13]:
          - generic [ref=e14]:
            - button "Dashboard" [ref=e15] [cursor=pointer]:
              - img [ref=e18]
              - generic [ref=e23]: Dashboard
            - button "Roadmap" [ref=e24] [cursor=pointer]:
              - img [ref=e26]
              - generic [ref=e30]: Roadmap
          - generic [ref=e31]:
            - paragraph [ref=e34]: CONTENT
            - button "Content Editor" [ref=e36] [cursor=pointer]:
              - img [ref=e38]
              - generic [ref=e42]: Content Editor
            - button "SEO Manager" [ref=e43] [cursor=pointer]:
              - img [ref=e45]
              - generic [ref=e48]: SEO Manager
            - button "Vertex AI Studio" [ref=e49] [cursor=pointer]:
              - img [ref=e51]
              - generic [ref=e54]: Vertex AI Studio
            - button "Automation" [ref=e55] [cursor=pointer]:
              - img [ref=e57]
              - generic [ref=e59]: Automation
          - generic [ref=e60]:
            - paragraph [ref=e63]: AUDIENCE
            - button "Users" [ref=e65] [cursor=pointer]:
              - img [ref=e67]
              - generic [ref=e72]: Users
            - button "Conversations" [ref=e73] [cursor=pointer]:
              - img [ref=e75]
              - generic [ref=e77]: Conversations
            - button "Chat Feedback" [ref=e78] [cursor=pointer]:
              - img [ref=e80]
              - generic [ref=e82]: Chat Feedback
          - generic [ref=e83]:
            - paragraph [ref=e86]: INSIGHTS
            - button "Analytics" [ref=e88] [cursor=pointer]:
              - img [ref=e90]
              - generic [ref=e93]: Analytics
            - button "Monetization" [ref=e94] [cursor=pointer]:
              - img [ref=e96]
              - generic [ref=e98]: Monetization
            - button "Ad Revenue" [ref=e99] [cursor=pointer]:
              - img [ref=e101]
              - generic [ref=e102]: Ad Revenue
            - button "Plans & Credits" [ref=e103] [cursor=pointer]:
              - img [ref=e105]
              - generic [ref=e107]: Plans & Credits
            - button "Intelligence" [ref=e108] [cursor=pointer]:
              - img [ref=e110]
              - generic [ref=e111]: Intelligence
          - generic [ref=e112]:
            - paragraph [ref=e115]: COMMS
            - button "Notifications" [ref=e117] [cursor=pointer]:
              - img [ref=e119]
              - generic [ref=e122]: Notifications
          - generic [ref=e123]:
            - paragraph [ref=e126]: SYSTEM
            - button "API Config" [ref=e128] [cursor=pointer]:
              - img [ref=e130]
              - generic [ref=e134]: API Config
            - button "Google Auth" [ref=e135] [cursor=pointer]:
              - img [ref=e137]
              - generic [ref=e139]: Google Auth
            - button "Site Settings" [ref=e140] [cursor=pointer]:
              - img [ref=e142]
              - generic [ref=e145]: Site Settings
            - button "Edu Browser" [ref=e146] [cursor=pointer]:
              - img [ref=e148]
              - generic [ref=e151]: Edu Browser
            - button "Rate Limits" [ref=e152] [cursor=pointer]:
              - img [ref=e154]
              - generic [ref=e156]: Rate Limits
            - button "Activity Log" [ref=e157] [cursor=pointer]:
              - img [ref=e159]
              - generic [ref=e161]: Activity Log
            - button "Bot Security" [ref=e162] [cursor=pointer]:
              - img [ref=e164]
              - generic [ref=e166]: Bot Security
            - button "Logs Explorer" [ref=e167] [cursor=pointer]:
              - img [ref=e169]
              - generic [ref=e171]: Logs Explorer
            - button "Health / Uptime" [ref=e172] [cursor=pointer]:
              - img [ref=e174]
              - generic [ref=e177]: Health / Uptime
        - generic [ref=e178]:
          - generic [ref=e179]:
            - generic [ref=e181]: E
            - generic [ref=e182]:
              - paragraph [ref=e183]: E2E Admin
              - paragraph [ref=e184]: e2e-admin@syrabit.ai
          - link "Student View" [ref=e185] [cursor=pointer]:
            - /url: /library
            - button "Student View" [ref=e186]:
              - img [ref=e187]
              - generic [ref=e191]: Student View
          - button "Logout" [ref=e192] [cursor=pointer]:
            - img [ref=e193]
            - generic [ref=e196]: Logout
          - button [ref=e197] [cursor=pointer]:
            - img [ref=e198]
      - generic [ref=e200]:
        - banner [ref=e201]:
          - generic [ref=e202]:
            - heading "Dashboard" [level=1] [ref=e203]
            - generic [ref=e204]: "|"
            - generic [ref=e205]: Syrabit.ai
          - generic [ref=e208]: All Systems Operational
        - main [ref=e209]:
          - generic [ref=e210]:
            - generic [ref=e211]:
              - generic [ref=e212]:
                - heading "Overview" [level=2] [ref=e213]
                - paragraph [ref=e214]: Updated just now · auto-refreshes every 60s
              - button "Refresh" [ref=e216] [cursor=pointer]:
                - img [ref=e217]
                - text: Refresh
            - generic [ref=e222]:
              - generic [ref=e223]:
                - generic [ref=e224]:
                  - paragraph [ref=e225]: Total Users
                  - img [ref=e227]
                - paragraph [ref=e232]: "0"
                - paragraph [ref=e233]: "Chatted: 0"
              - generic [ref=e234]:
                - generic [ref=e235]:
                  - paragraph [ref=e236]: Conversations
                  - img [ref=e238]
                - paragraph [ref=e240]: "0"
                - paragraph [ref=e241]: "With messages: 0"
              - generic [ref=e242]:
                - generic [ref=e243]:
                  - paragraph [ref=e244]: Messages (All)
                  - img [ref=e246]
                - paragraph [ref=e248]: "0"
                - paragraph [ref=e249]: "Since: —"
              - generic [ref=e250]:
                - generic [ref=e251]:
                  - paragraph [ref=e252]: Subjects
                  - img [ref=e254]
                - paragraph [ref=e256]: "0"
            - generic [ref=e258]:
              - generic [ref=e259]:
                - img [ref=e260]
                - generic [ref=e263]: Traffic (Cloudflare)
                - link "Account analytics documentation" [ref=e264] [cursor=pointer]:
                  - /url: https://dash.cloudflare.com/?to=/:account/analytics
                - generic [ref=e265]: All sites for account · Previous 7 days
              - generic [ref=e266]:
                - button "24H" [ref=e267] [cursor=pointer]
                - button "7D" [ref=e268] [cursor=pointer]
                - button "30D" [ref=e269] [cursor=pointer]
              - paragraph [ref=e270]: Today = 00:00 UTC → now (5:30 AM IST → now IST)
              - generic [ref=e271]:
                - generic [ref=e272]:
                  - paragraph [ref=e273]: Interactions
                  - paragraph [ref=e274]: —
                  - paragraph [ref=e275]: "Today: —"
                - generic [ref=e277]:
                  - paragraph [ref=e278]: Bandwidth
                  - paragraph [ref=e279]: —
                  - paragraph [ref=e280]: "Today: —"
                - generic [ref=e282]:
                  - paragraph [ref=e283]: Total Visitors
                  - paragraph [ref=e284]: —
                  - paragraph [ref=e285]: "Today: —"
                - generic [ref=e287]:
                  - paragraph [ref=e288]: Page views
                  - paragraph [ref=e289]: —
                  - paragraph [ref=e290]: "Today: —"
            - generic [ref=e292]:
              - paragraph [ref=e293]: Today = 00:00 UTC → now (5:30 AM IST → now IST)
              - generic [ref=e294]:
                - generic [ref=e295]:
                  - generic [ref=e299]:
                    - paragraph [ref=e300]: Page Views Today
                    - img [ref=e302]
                  - paragraph [ref=e305]: "0"
                - generic [ref=e306]:
                  - generic [ref=e307]:
                    - paragraph [ref=e308]: Total Visitors
                    - img [ref=e310]
                  - paragraph [ref=e315]: "0"
                  - paragraph [ref=e316]: "Today: 0"
                - generic [ref=e317]:
                  - generic [ref=e318]:
                    - paragraph [ref=e319]: Bounce Rate
                    - img [ref=e321]
                  - paragraph [ref=e324]: —
                - generic [ref=e325]:
                  - generic [ref=e326]:
                    - paragraph [ref=e327]: Avg Session
                    - img [ref=e329]
                  - paragraph [ref=e332]: —
            - generic [ref=e334]:
              - generic [ref=e335]:
                - img [ref=e336]
                - heading "Cloudflare Search Crawler Activity" [level=3] [ref=e339]
                - generic [ref=e341]: CF analytics unavailable
              - generic [ref=e342]:
                - img [ref=e343]
                - generic [ref=e345]: Cloudflare GraphQL API did not return verified-bot data.
            - generic [ref=e347]:
              - generic [ref=e348]:
                - img [ref=e349]
                - heading "SEO Sitemap Health" [level=3] [ref=e353]
                - button "Probe now" [ref=e354] [cursor=pointer]:
                  - img [ref=e355]
                  - text: Probe now
              - generic [ref=e360]:
                - img [ref=e361]
                - text: Loading sitemap probes…
            - generic [ref=e364]:
              - generic [ref=e365]:
                - img [ref=e366]
                - heading "Alert History" [level=3] [ref=e368]
                - generic [ref=e369]:
                  - button "Sound On" [ref=e370] [cursor=pointer]:
                    - img [ref=e371]
                    - text: Sound On
                  - button "Loading..." [disabled] [ref=e375]:
                    - img [ref=e376]
                    - text: Loading...
                  - combobox [ref=e381]:
                    - option "All alerts" [selected]
                    - option "Unacknowledged"
                    - option "Acknowledged"
                  - generic "Include synthetic alerts produced by the Test alert delivery button" [ref=e382] [cursor=pointer]:
                    - checkbox "Show test alerts" [ref=e383]
                    - text: Show test alerts
                  - button "Settings" [ref=e384] [cursor=pointer]:
                    - img [ref=e385]
                    - text: Settings
                  - button "Preferences" [ref=e388] [cursor=pointer]:
                    - img [ref=e389]
                    - text: Preferences
              - paragraph [ref=e392]: No alerts have been triggered yet. Alerts appear here when system thresholds are exceeded.
            - generic [ref=e394]:
              - generic [ref=e395]:
                - img [ref=e396]
                - heading "IndexNow Push Status" [level=3] [ref=e399]
                - button "Re-submit recent URLs to search engines" [ref=e400] [cursor=pointer]:
                  - img [ref=e401]
                  - text: Re-submit recent URLs to search engines
              - generic [ref=e404]:
                - generic [ref=e405]:
                  - paragraph [ref=e406]: "0"
                  - paragraph [ref=e407]: Total URLs Pushed
                - generic [ref=e408]:
                  - paragraph [ref=e409]: "0"
                  - paragraph [ref=e410]: Total Pushes
                - generic "Today = 00:00 UTC → now (5:30 AM IST → now IST)" [ref=e411]:
                  - paragraph [ref=e412]: "0"
                  - paragraph [ref=e413]: URLs Today (UTC)
                - generic [ref=e414]:
                  - paragraph [ref=e415]: "0"
                  - paragraph [ref=e416]: Pending
            - generic [ref=e418]:
              - generic [ref=e419]:
                - img [ref=e420]
                - heading "AI Health" [level=3] [ref=e423]
                - generic [ref=e425]: GREEN
              - generic [ref=e426]:
                - generic [ref=e427]:
                  - generic [ref=e428]:
                    - generic [ref=e429]:
                      - img [ref=e430]
                      - text: RAG Accuracy
                    - generic [ref=e434]: GREEN
                  - img [ref=e436]:
                    - generic [ref=e439]: 98.0%
                    - generic [ref=e440]: "Target: 98%"
                  - paragraph [ref=e441]: No queries yet — showing default
                - generic [ref=e442]:
                  - generic [ref=e443]:
                    - generic [ref=e444]:
                      - img [ref=e445]
                      - text: Daily Fallback Rate
                    - generic [ref=e447]: GREEN
                  - generic [ref=e448]:
                    - img [ref=e449]
                    - generic [ref=e451]: No query data yet
                    - generic [ref=e452]: 0% fallback rate
                  - paragraph [ref=e453]: "Target: <5% fallback rate"
                - generic [ref=e454]:
                  - generic [ref=e455]:
                    - generic [ref=e456]:
                      - img [ref=e457]
                      - text: Vector Coverage
                    - generic [ref=e461]: GREEN
                  - generic [ref=e462]:
                    - generic [ref=e464]:
                      - generic [ref=e465]: SEO Pages
                      - generic [ref=e466]: 0%
                    - generic [ref=e469]:
                      - generic [ref=e470]: Chapters
                      - generic [ref=e471]: 0%
                    - generic [ref=e474]:
                      - generic [ref=e475]: Overall
                      - generic [ref=e476]: 0%
                    - paragraph [ref=e478]: 0 / 0 items embedded
                  - paragraph [ref=e479]: "Target: ≥90%"
            - generic [ref=e481]:
              - generic [ref=e482]:
                - generic [ref=e483]:
                  - img [ref=e484]
                  - heading "Chat Speed-up Scoreboard" [level=3] [ref=e486]
                  - generic [ref=e487]: cache & speculative-web impact
                - generic [ref=e488]:
                  - button "24h" [ref=e489] [cursor=pointer]
                  - button "7d" [ref=e490] [cursor=pointer]
                  - button "14d" [ref=e491] [cursor=pointer]
                  - button "30d" [ref=e492] [cursor=pointer]
              - generic [ref=e493]:
                - generic [ref=e494]:
                  - generic [ref=e495]:
                    - paragraph [ref=e496]: Cache hit
                    - paragraph [ref=e497]: 0%
                    - paragraph [ref=e498]: 0 hits
                  - generic [ref=e499]:
                    - paragraph [ref=e500]: Warmed cache
                    - paragraph [ref=e501]: 0%
                    - paragraph [ref=e502]: 0 early
                  - generic [ref=e503]:
                    - paragraph [ref=e504]: Speculative web used
                    - paragraph [ref=e505]: 0%
                    - paragraph [ref=e506]: 0 / 0
                  - generic [ref=e507]:
                    - paragraph [ref=e508]: Avg TTFB
                    - paragraph [ref=e509]: 0ms
                    - paragraph [ref=e510]: 0 samples
                - generic [ref=e511]:
                  - generic [ref=e512]:
                    - generic [ref=e513]:
                      - generic [ref=e514]: Cache hit % · Avg TTFB
                      - generic [ref=e515]: 0 chats
                    - generic [ref=e516]:
                      - img [ref=e517]
                      - generic [ref=e519]: No chat speed-up data yet
                      - generic [ref=e520]: Populates after chats are served
                  - generic [ref=e521]:
                    - generic [ref=e522]:
                      - generic [ref=e523]:
                        - img [ref=e524]
                        - text: Recent cache-warm runs
                      - generic [ref=e529]: 6h pre-warm cycle
                    - generic [ref=e530]:
                      - img [ref=e531]
                      - generic [ref=e536]: No warm runs in window
                      - generic [ref=e537]: Pre-warm cycle runs every 6h
                - generic [ref=e538]:
                  - generic [ref=e539]:
                    - generic [ref=e540]: Per-provider chat speed
                    - generic [ref=e541]: Vertex Gemini vs legacy SLM pool · 2 providers
                  - table [ref=e543]:
                    - rowgroup [ref=e544]:
                      - row "Provider Calls Avg TTFT ms Avg total ms Tokens / sec" [ref=e545]:
                        - columnheader "Provider" [ref=e546]
                        - columnheader "Calls" [ref=e547]
                        - columnheader "Avg TTFT ms" [ref=e548]
                        - columnheader "Avg total ms" [ref=e549]
                        - columnheader "Tokens / sec" [ref=e550]
                    - rowgroup [ref=e551]:
                      - row "vertex_geminihappy path 0 — — —" [ref=e552]:
                        - cell "vertex_geminihappy path" [ref=e553]: vertex_geminihappy path
                        - cell "0" [ref=e555]
                        - cell "—" [ref=e556]
                        - cell "—" [ref=e557]
                        - cell "—" [ref=e558]
                      - row "openai/gpt-oss-20b 0 — — —" [ref=e559]:
                        - cell "openai/gpt-oss-20b" [ref=e560]: openai/gpt-oss-20b
                        - cell "0" [ref=e562]
                        - cell "—" [ref=e563]
                        - cell "—" [ref=e564]
                        - cell "—" [ref=e565]
                  - generic [ref=e566]:
                    - generic [ref=e567]: Fallbacks (Vertex → legacy)
                    - generic [ref=e568]: 0 in window
                  - generic [ref=e569]: No fallbacks recorded — Vertex served every chat in this window.
                - generic [ref=e570]:
                  - generic [ref=e571]:
                    - generic [ref=e572]: Per-day breakdown
                    - generic [ref=e573]: 0 days
                  - generic [ref=e575]: No per-day data in window
                - paragraph [ref=e576]: "Window: last 7 days"
            - generic [ref=e578]:
              - generic [ref=e579]:
                - generic [ref=e580]:
                  - img [ref=e581]
                  - heading "Anonymous Quota Wall" [level=3] [ref=e583]
                  - generic [ref=e584]: device 30/day cap hits & sign-up rescue
                - generic [ref=e585]:
                  - generic [ref=e586]:
                    - button "24h" [ref=e587] [cursor=pointer]
                    - button "7d" [ref=e588] [cursor=pointer]
                    - button "14d" [ref=e589] [cursor=pointer]
                  - button "Backfill today" [ref=e590] [cursor=pointer]:
                    - img [ref=e591]
                    - text: Backfill today
              - generic [ref=e594]:
                - generic [ref=e595]:
                  - generic [ref=e596]:
                    - img [ref=e597]
                    - text: Wall hits
                  - generic [ref=e599]: "0"
                  - generic [ref=e600]: events in window
                - generic [ref=e601]:
                  - generic [ref=e602]:
                    - img [ref=e603]
                    - text: Unique devices
                  - generic [ref=e605]: "0"
                  - generic [ref=e606]: distinct cookies
                - generic [ref=e607]:
                  - generic [ref=e608]:
                    - img [ref=e609]
                    - text: Signed up
                  - generic [ref=e613]: "0"
                  - generic [ref=e614]: within 24h of wall
                - generic [ref=e615]:
                  - generic [ref=e616]:
                    - img [ref=e617]
                    - text: Conversion
                  - generic [ref=e621]: 0.0%
                  - generic [ref=e622]: wall → sign-up
              - generic [ref=e623]:
                - generic [ref=e624]:
                  - generic [ref=e625]: Daily wall hits & conversion
                  - generic [ref=e627]: exhausted
                - generic [ref=e629]:
                  - img [ref=e630]
                  - generic [ref=e632]: No wall hits in the last 7 days
                  - generic [ref=e633]:
                    - text: Click
                    - strong [ref=e634]: Backfill today
                    - text: if devices have already hit the cap before this card shipped
              - generic [ref=e635]:
                - generic [ref=e636]:
                  - generic [ref=e637]: By hour of day (UTC)
                  - generic [ref=e638]: when devices hit the wall
                - generic [ref=e639]:
                  - generic "00:00 — 0 hits" [ref=e640]:
                    - generic [ref=e641]: "00"
                  - generic "01:00 — 0 hits" [ref=e642]
                  - generic "02:00 — 0 hits" [ref=e643]
                  - generic "03:00 — 0 hits" [ref=e644]:
                    - generic [ref=e645]: "03"
                  - generic "04:00 — 0 hits" [ref=e646]
                  - generic "05:00 — 0 hits" [ref=e647]
                  - generic "06:00 — 0 hits" [ref=e648]:
                    - generic [ref=e649]: "06"
                  - generic "07:00 — 0 hits" [ref=e650]
                  - generic "08:00 — 0 hits" [ref=e651]
                  - generic "09:00 — 0 hits" [ref=e652]:
                    - generic [ref=e653]: "09"
                  - generic "10:00 — 0 hits" [ref=e654]
                  - generic "11:00 — 0 hits" [ref=e655]
                  - generic "12:00 — 0 hits" [ref=e656]:
                    - generic [ref=e657]: "12"
                  - generic "13:00 — 0 hits" [ref=e658]
                  - generic "14:00 — 0 hits" [ref=e659]
                  - generic "15:00 — 0 hits" [ref=e660]:
                    - generic [ref=e661]: "15"
                  - generic "16:00 — 0 hits" [ref=e662]
                  - generic "17:00 — 0 hits" [ref=e663]
                  - generic "18:00 — 0 hits" [ref=e664]:
                    - generic [ref=e665]: "18"
                  - generic "19:00 — 0 hits" [ref=e666]
                  - generic "20:00 — 0 hits" [ref=e667]
                  - generic "21:00 — 0 hits" [ref=e668]:
                    - generic [ref=e669]: "21"
                  - generic "22:00 — 0 hits" [ref=e670]
                  - generic "23:00 — 0 hits" [ref=e671]
                - generic [ref=e672]:
                  - generic [ref=e673]: By day of week (UTC)
                  - generic [ref=e674]:
                    - generic [ref=e675]:
                      - generic [ref=e677]: "0"
                      - text: Mon
                    - generic [ref=e678]:
                      - generic [ref=e680]: "0"
                      - text: Tue
                    - generic [ref=e681]:
                      - generic [ref=e683]: "0"
                      - text: Wed
                    - generic [ref=e684]:
                      - generic [ref=e686]: "0"
                      - text: Thu
                    - generic [ref=e687]:
                      - generic [ref=e689]: "0"
                      - text: Fri
                    - generic [ref=e690]:
                      - generic [ref=e692]: "0"
                      - text: Sat
                    - generic [ref=e693]:
                      - generic [ref=e695]: "0"
                      - text: Sun
              - paragraph [ref=e696]: "Window: last 7 days"
            - generic [ref=e697]:
              - generic [ref=e699]:
                - generic [ref=e700]:
                  - generic [ref=e701]:
                    - img [ref=e702]
                    - heading "Query Latency P95" [level=3] [ref=e705]
                  - generic [ref=e706]:
                    - generic [ref=e707]:
                      - text: "P95:"
                      - generic [ref=e708]: 0ms
                    - generic [ref=e709]: GREEN
                - generic [ref=e710]:
                  - img [ref=e711]
                  - generic [ref=e714]: No latency data yet
                  - generic [ref=e715]: Data recorded after first chat
                - paragraph [ref=e716]: "Target: P95 <2 s · Avg: 0ms"
              - generic [ref=e718]:
                - generic [ref=e719]:
                  - img [ref=e720]
                  - heading "Top Queries" [level=3] [ref=e723]
                  - generic [ref=e724]: content gap signal
                - generic [ref=e725]:
                  - img [ref=e726]
                  - generic [ref=e729]: No query data yet
                  - generic [ref=e730]: Populates after user chats
                - paragraph [ref=e731]: 0 unique queries in last 7 days
            - generic [ref=e732]:
              - generic [ref=e734]:
                - generic [ref=e735]:
                  - img [ref=e736]
                  - heading "Token Spend" [level=3] [ref=e739]
                - generic [ref=e740]:
                  - img [ref=e741]
                  - generic [ref=e742]: No token data yet
                  - generic [ref=e743]: Grows with AI usage
              - generic [ref=e745]:
                - generic [ref=e746]:
                  - img [ref=e747]
                  - heading "Conversion Funnel" [level=3] [ref=e750]
                - generic [ref=e752]:
                  - generic [ref=e753]:
                    - paragraph [ref=e754]: "%"
                    - paragraph [ref=e755]: Free→Paid
                  - generic [ref=e756]:
                    - paragraph [ref=e757]: "%"
                    - paragraph [ref=e758]: Starter→Pro
              - generic [ref=e760]:
                - generic [ref=e761]:
                  - img [ref=e762]
                  - heading "Assam Board Coverage" [level=3] [ref=e766]
                  - generic [ref=e767]: chapter × subject
                - generic [ref=e768]:
                  - img [ref=e769]
                  - generic [ref=e771]: No subjects found
                  - generic [ref=e772]: Add subjects to see coverage
                - generic [ref=e773]:
                  - generic [ref=e776]: Full
                  - generic [ref=e779]: Partial
                  - generic [ref=e782]: None
            - generic [ref=e784]:
              - generic [ref=e785]:
                - img [ref=e786]
                - heading "PWA App Downloads" [level=3] [ref=e788]
              - generic [ref=e789]:
                - generic [ref=e790]:
                  - paragraph
                  - paragraph [ref=e791]: Total Installs
                - generic [ref=e792]:
                  - paragraph
                  - paragraph [ref=e793]: Last 7 Days
                - generic [ref=e794]:
                  - paragraph
                  - paragraph [ref=e795]: Prompts Shown
                - generic [ref=e796]:
                  - paragraph [ref=e797]: undefined%
                  - paragraph [ref=e798]: Install Rate
              - generic [ref=e799]:
                - generic [ref=e800]: "Dismissed: 0"
                - generic [ref=e801]: "Rejected: 0"
            - generic [ref=e803]:
              - generic [ref=e805]:
                - img [ref=e806]
                - heading "Content Pipeline" [level=3] [ref=e810]
                - generic [ref=e811]: ( topics · pages)
              - generic [ref=e812]:
                - generic [ref=e814]:
                  - generic [ref=e815]: Published
                  - generic [ref=e816]: (NaN%)
                - generic [ref=e820]:
                  - generic [ref=e821]: Has Content
                  - generic [ref=e822]: (NaN%)
                - generic [ref=e826]:
                  - generic [ref=e827]: Needs Schema
                  - generic [ref=e828]: (NaN%)
                - generic [ref=e832]:
                  - generic [ref=e833]: Needs Links
                  - generic [ref=e834]: (NaN%)
            - generic [ref=e837]:
              - button "View Users" [ref=e838] [cursor=pointer]:
                - generic [ref=e839]:
                  - img [ref=e841]
                  - generic [ref=e846]: View Users
                - img [ref=e847]
              - button "Blog Publisher" [ref=e849] [cursor=pointer]:
                - generic [ref=e850]:
                  - img [ref=e852]
                  - generic [ref=e857]: Blog Publisher
                - img [ref=e858]
              - button "Analytics" [ref=e860] [cursor=pointer]:
                - generic [ref=e861]:
                  - img [ref=e863]
                  - generic [ref=e864]: Analytics
                - img [ref=e865]
              - button "Monetization" [ref=e867] [cursor=pointer]:
                - generic [ref=e868]:
                  - img [ref=e870]
                  - generic [ref=e872]: Monetization
                - img [ref=e873]
            - generic [ref=e876]:
              - generic [ref=e877]:
                - generic [ref=e878]:
                  - img [ref=e879]
                  - heading "Recent Activity" [level=3] [ref=e881]
                - button "View all logs →" [ref=e885] [cursor=pointer]
              - generic [ref=e886]:
                - img [ref=e887]
                - paragraph [ref=e889]: No activity yet — events will appear here in real time
            - generic [ref=e890]:
              - generic [ref=e891]:
                - generic [ref=e892]:
                  - img [ref=e894]
                  - generic [ref=e896]:
                    - heading "Subjects served as draft" [level=3] [ref=e897]
                    - paragraph [ref=e898]: Live chapter URLs are rendering even though the subject status isn't "published".
                - button "Refresh draft-served subjects" [ref=e899] [cursor=pointer]:
                  - img [ref=e900]
                  - text: Refresh
              - generic [ref=e905]:
                - img [ref=e906]
                - paragraph [ref=e909]: All subjects published — nothing to do
            - generic [ref=e910]:
              - paragraph [ref=e911]: Related Sections
              - generic [ref=e912]:
                - button "Content" [ref=e913] [cursor=pointer]:
                  - img [ref=e914]
                  - text: Content
                - button "SEO Manager" [ref=e916] [cursor=pointer]:
                  - img [ref=e917]
                  - text: SEO Manager
                - button "Analytics" [ref=e920] [cursor=pointer]:
                  - img [ref=e921]
                  - text: Analytics
                - button "Users" [ref=e924] [cursor=pointer]:
                  - img [ref=e925]
                  - text: Users
                - button "Conversations" [ref=e930] [cursor=pointer]:
                  - img [ref=e931]
                  - text: Conversations
                - button "Vertex AI" [ref=e933] [cursor=pointer]:
                  - img [ref=e934]
                  - text: Vertex AI
                - button "Monetization" [ref=e937] [cursor=pointer]:
                  - img [ref=e938]
                  - text: Monetization
    - region "Notifications alt+T"
```

# Test source

```ts
  142 |           (window as unknown as Record<string, unknown>).__permCalled = true;
  143 |           return 'granted';
  144 |         };
  145 | 
  146 |         if ('PushManager' in window) {
  147 |           (PushManager.prototype as unknown as { subscribe: unknown }).subscribe =
  148 |             async () => ({
  149 |               endpoint: fakeSub.endpoint,
  150 |               expirationTime: null,
  151 |               getKey: () => null,
  152 |               toJSON: () => ({
  153 |                 endpoint: fakeSub.endpoint,
  154 |                 expirationTime: null,
  155 |                 keys: fakeSub.keys,
  156 |               }),
  157 |               unsubscribe: async () => true,
  158 |             });
  159 |         }
  160 |       }, FAKE_SUBSCRIPTION);
  161 | 
  162 |       // Also stub PushManager.prototype.getSubscription to return null so the
  163 |       // mount effect in the hook reports subscribed=false immediately.
  164 |       await page.addInitScript(() => {
  165 |         if ('PushManager' in window) {
  166 |           (PushManager.prototype as unknown as { getSubscription: unknown }).getSubscription =
  167 |             async () => null;
  168 |         }
  169 |       });
  170 | 
  171 |       // Admin session bootstrap.
  172 |       await seedAdminSession(page);
  173 |       await installAdminApiMocks(page);
  174 | 
  175 |       // Intercept the VAPID key endpoint. 'AAAA' is valid minimal base64url
  176 |       // that urlBase64ToUint8Array in the hook can decode without error.
  177 |       await page.route('**/push/vapid-public-key', (route) =>
  178 |         route.fulfill({ json: { public_key: 'AAAA' } }),
  179 |       );
  180 | 
  181 |       // Capture the subscription POST body.
  182 |       let capturedBody: unknown = null;
  183 |       await page.route('**/push/subscribe', async (route) => {
  184 |         if (route.request().method() === 'POST') {
  185 |           const raw = route.request().postData();
  186 |           capturedBody = raw ? JSON.parse(raw) : null;
  187 |           await route.fulfill({ json: { ok: true } });
  188 |         } else {
  189 |           await route.continue();
  190 |         }
  191 |       });
  192 | 
  193 |       // Pre-register the service worker so navigator.serviceWorker.ready
  194 |       // resolves immediately when the hook awaits it after permission is granted.
  195 |       // We do this at the initial '/' load before navigating to /admin.
  196 |       await page.goto('/');
  197 |       await page.waitForLoadState('domcontentloaded');
  198 |       await page.evaluate(async () => {
  199 |         if (!('serviceWorker' in navigator)) return;
  200 |         const reg = await navigator.serviceWorker.register('/sw.js', {
  201 |           updateViaCache: 'none',
  202 |         });
  203 |         // The SW calls skipWaiting() in install, so it becomes active quickly.
  204 |         // Wait for it to be the active controller before we navigate away.
  205 |         await new Promise<void>((resolve) => {
  206 |           if (navigator.serviceWorker.controller) {
  207 |             resolve();
  208 |             return;
  209 |           }
  210 |           navigator.serviceWorker.addEventListener('controllerchange', () => resolve(), {
  211 |             once: true,
  212 |           });
  213 |           // Fallback: if controllerchange never fires, resolve after 2s
  214 |           // (the SW is installed/waiting even if not controlling yet, so
  215 |           // navigator.serviceWorker.ready will still resolve on /admin).
  216 |           setTimeout(resolve, 2000);
  217 |         });
  218 |       });
  219 | 
  220 |       // Now navigate to /admin with the SW in place.
  221 |       await page.goto('/admin');
  222 |       await expect(page.getByTestId('admin-dashboard')).toBeVisible();
  223 | 
  224 |       const pushBtn = await getPushToggle(page);
  225 |       await expect(pushBtn).toBeVisible();
  226 | 
  227 |       // Click the real push toggle → triggers the hook's subscribe():
  228 |       //   requestPermission() → 'granted'
  229 |       //   fetch /api/push/vapid-public-key → 'AAAA'
  230 |       //   navigator.serviceWorker.ready → active SW (pre-registered above)
  231 |       //   pushManager.subscribe() → FAKE_SUBSCRIPTION (stubbed)
  232 |       //   POST /api/push/subscribe → captured below
  233 |       await pushBtn.click();
  234 | 
  235 |       // requestPermission must have been called by the hook.
  236 |       const permCalled = await page.evaluate(
  237 |         () => (window as unknown as Record<string, unknown>).__permCalled as boolean,
  238 |       );
  239 |       expect(permCalled).toBe(true);
  240 | 
  241 |       // Wait for the POST to arrive (hook is async).
> 242 |       await expect
      |       ^ Error: expect(received).not.toBeNull()
  243 |         .poll(() => capturedBody, { timeout: 8000 })
  244 |         .not.toBeNull();
  245 | 
  246 |       // Assert the request body has the correct subscription shape.
  247 |       const body = capturedBody as {
  248 |         subscription: { endpoint: string; keys: { p256dh: string; auth: string } };
  249 |       };
  250 |       expect(body.subscription).toBeDefined();
  251 |       expect(body.subscription.endpoint).toBe(FAKE_SUBSCRIPTION.endpoint);
  252 |       expect(body.subscription.keys.p256dh).toBe(FAKE_SUBSCRIPTION.keys.p256dh);
  253 |       expect(body.subscription.keys.auth).toBe(FAKE_SUBSCRIPTION.keys.auth);
  254 |     },
  255 |   );
  256 | 
  257 |   test(
  258 |     'baseline: Notification.permission is "default" at page load (app does not pre-request it)',
  259 |     async ({ page }) => {
  260 |       // No grantPermissions, no stubs — read the raw browser permission state.
  261 |       // The app must not call requestPermission() automatically at load time;
  262 |       // it should only be triggered by an explicit user action (the push toggle).
  263 |       await page.goto('/');
  264 |       await page.waitForLoadState('domcontentloaded');
  265 | 
  266 |       const permission = await page.evaluate(() => Notification.permission);
  267 | 
  268 |       // A fresh context without any action must be 'default' (prompt-able),
  269 |       // not 'denied' (which would block the hook forever) or 'granted'
  270 |       // (which the app must only acquire after the user explicitly enables push).
  271 |       expect(permission).toBe('default');
  272 |     },
  273 |   );
  274 | });
  275 | 
```