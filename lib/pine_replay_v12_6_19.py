"""
Faithful Python replay of DNA v12.6.19's event engine.

Ported line-by-line from the frozen Pine source (Pine/DNA_v12.6.19.pine),
default input values only (no tuning -- Test 5A feasibility forbids it).
Purpose is reconstruction VALIDATION, not signal generation: we replay the
engine on the exported OHLCV and compare the events we produce against the
`Event: *` columns Pine itself exported.

Scope note: the nine events under study are all SINGLE-TIMEFRAME. Verified
by reading the source -- `request.security()` appears only in the dashboard
HTF-phase row and the cross-TF alignment/fail-cluster blocks (lines ~1070,
1107-1131), none of which feed strongStartEvent / campaignStartEvent /
addEvent / ignitionEvent / premiumEvent / manageEvent / peakEvent /
failEvent / failTestEvent / reloadDisplayEvent. So a per-timeframe replay is
structurally complete for these events, with no cross-TF dependency.

Known irreducible limitation, quantified in the feasibility report: Pine's
state at the first exported bar reflects chart history BEFORE the export
window (both indicator warm-up and unbounded campaign memory). This replay
starts cold at bar 0 and therefore cannot match Pine over the burn-in
region; comparison is restricted to post-burn-in bars.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

NA = float("nan")


def _ema(v, n):
    a = 2.0 / (n + 1)
    out = np.full(len(v), np.nan)
    if len(v) < n:
        return out
    out[n - 1] = v[:n].mean()
    for i in range(n, len(v)):
        out[i] = a * v[i] + (1 - a) * out[i - 1]
    return out


def _rma(v, n):
    """Pine's ta.rma (Wilder). Used by ta.rsi and ta.atr."""
    a = 1.0 / n
    out = np.full(len(v), np.nan)
    if len(v) < n:
        return out
    out[n - 1] = np.nanmean(v[:n])
    for i in range(n, len(v)):
        out[i] = a * v[i] + (1 - a) * out[i - 1]
    return out


def _rsi(close, n):
    d = np.diff(close, prepend=close[0])
    d[0] = np.nan
    up = np.where(d > 0, d, 0.0); up[0] = np.nan
    dn = np.where(d < 0, -d, 0.0); dn[0] = np.nan
    ru = _rma(up[1:], n); rd = _rma(dn[1:], n)
    ru = np.concatenate([[np.nan], ru]); rd = np.concatenate([[np.nan], rd])
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = ru / rd
        out = 100 - 100 / (1 + rs)
    out = np.where(rd == 0, 100.0, out)
    out = np.where(ru == 0, 0.0, out)
    return out


def _sma(v, n):
    return pd.Series(v).rolling(n).mean().to_numpy()


def _stdev(v, n):
    # Pine ta.stdev is population (ddof=0)
    return pd.Series(v).rolling(n).std(ddof=0).to_numpy()


def _atr(high, low, close, n=14):
    prev = np.concatenate([[np.nan], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    tr[0] = high[0] - low[0]
    return _rma(tr, n)


def _lowest(v, n):
    return pd.Series(v).rolling(n).min().to_numpy()


def _highest(v, n):
    return pd.Series(v).rolling(n).max().to_numpy()


def _prev(a, fill=np.nan):
    return np.concatenate([[fill], a[:-1]])


def replay(df: pd.DataFrame, tf_minutes: int) -> pd.DataFrame:
    """Replay the engine over one (asset, source, timeframe) frame.
    `df` must carry open/high/low/close/Volume, sorted, deduplicated."""
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float); c = df["close"].to_numpy(float)
    vol = df["Volume"].to_numpy(float)
    n = len(c)
    tf_hours = tf_minutes / 60.0
    is_intraday = tf_minutes < 1440

    # ---- inputs (Pine defaults, untouched) ----
    rsiLen, volLen, bbLen, bbMult = 14, 20, 20, 2.0
    signalCooldown, accumulateCooldown, manageCooldown, memoryBars = 8, 10, 6, 24
    accumulateMinScore, addMinScore = 62, 68
    premiumMemoryBars, failureConfirmBars = 12, 3
    peakWindowBars, peakCooldownBars, premiumCooldownBars = 24, 18, 24
    premiumRsiMin, premiumExtensionAtr = 67, 1.45
    strengthMax, strengthFailProtection, strongCampaignLevel = 8, 5, 3
    peakMaturityStrength, peakMaturityAdds = 4, 3
    relax4HSignals, adaptiveResolution = True, True
    resolutionBars, manualResolutionMinBars = 6, 3
    resolutionConfirmScore, resolutionFailScore = 3, -3
    healthSmoothLen, healthFailTestLevel, healthEmergencyLevel = 3, 42, 22
    reloadWindowBars, reloadMinVolume = 6, 0.90
    reloadScoreRecovery, reloadHealthRecovery = 5, 10
    postFailRecoveryBars, postFailHealthRecovery, postFailRecoveryScoreMin = 20, 8, 70
    maturityPeakScore = 68

    ignitionVolMin = 1.08 if tf_hours >= 4 else 1.30 if tf_hours >= 2 else 1.35 if tf_hours <= 0.5 else 1.45
    addVolMin = 1.08 if tf_hours >= 4 else 1.14 if tf_hours >= 2 else 1.15 if tf_hours <= 0.5 else 1.20
    premiumVolMin = 1.25 if tf_hours >= 4 else 1.35 if tf_hours >= 2 else 1.45
    premiumAtrFactor = 1.35 if tf_hours >= 4 else 1.40 if tf_hours >= 2 else 1.50
    adaptiveMinBars = 4 if (is_intraday and tf_hours <= 0.5) else 3 if (is_intraday and tf_hours <= 1.0) else 2
    resolutionMinBars = adaptiveMinBars if adaptiveResolution else manualResolutionMinBars
    healthTolerance = (12 if (is_intraday and tf_hours <= 0.5) else 8 if (is_intraday and tf_hours <= 1.0)
                       else 4 if (is_intraday and tf_hours <= 2.0) else 0)
    isRelaxedTimeframe = is_intraday and tf_hours >= 3
    ageMatureBars = (5 if not is_intraday else 8 if tf_hours >= 4 else 12 if tf_hours >= 2 else 18 if tf_hours >= 1 else 24)

    # ---- vectorized indicators ----
    rsi = _rsi(c, rsiLen)
    ema21, ema50, ema100, ema200 = _ema(c, 21), _ema(c, 50), _ema(c, 100), _ema(c, 200)
    ema21Slope = ema21 - np.concatenate([np.full(5, np.nan), ema21[:-5]])
    ema50Slope = ema50 - np.concatenate([np.full(5, np.nan), ema50[:-5]])
    avgVol = _sma(vol, volLen)
    volRatio = np.where(avgVol > 0, vol / avgVol, 0.0)
    atr = _atr(h, l, c, 14)
    atrPct = np.where(c != 0, atr / c * 100, 0.0)
    atrPctAvg = _sma(atrPct, 20)
    bbBasis = _sma(c, bbLen); bbDev = _stdev(c, bbLen) * bbMult
    bbUpper, bbLower = bbBasis + bbDev, bbBasis - bbDev
    bbWidth = np.where(bbBasis != 0, (bbUpper - bbLower) / bbBasis, 0.0)
    bbWidthAvg = _sma(bbWidth, 50)
    squeezeZone = bbWidth < bbWidthAvg * 0.85
    bbExpanding = (bbWidth > _prev(bbWidth)) & (bbWidth > bbWidthAvg * 0.90)
    recentLow, recentHigh = _lowest(l, 20), _highest(h, 20)
    swingLow, swingHigh = _lowest(l, 8), _highest(h, 8)
    lowestClose40 = _lowest(c, 40)
    recoveryLookback = min(postFailRecoveryBars, 10)
    recoveryLowestLow = _lowest(l, recoveryLookback)
    distanceFromEma21Atr = np.where(atr > 0, (c - ema21) / atr, 0.0)
    pullbackFromHighPct = np.where(recentHigh > 0, (recentHigh - c) / recentHigh * 100, 0.0)

    trendScore = ((c > ema200) * 8 + (c > ema50) * 8 + (ema21 > ema50) * 8 +
                  (ema50 > ema200) * 8 + (ema21Slope > 0) * 6 + (ema50Slope > 0) * 4)
    momentumScore = (((rsi >= 48) & (rsi <= 68)) * 12 + (rsi > _prev(rsi)) * 8 +
                     (c > _prev(c)) * 5 + (c > ema21) * 5)
    volumeScore = (volRatio >= 1.2) * 8 + (volRatio >= 1.5) * 6 + (vol > _prev(vol)) * 4
    structureScore = ((l > recentLow) * 5 + (c > swingLow) * 5 +
                      (distanceFromEma21Atr < 2.5) * 6 + (pullbackFromHighPct >= 1.0) * 4)
    compressionScore = squeezeZone * 8
    expansionScore = (bbExpanding & (c > bbBasis)) * 5
    campaignScore = np.clip(trendScore + momentumScore + volumeScore + structureScore +
                            compressionScore + expansionScore, 0, 100).astype(float)

    fourHourExpansionSetup = (isRelaxedTimeframe and relax4HSignals) & (
        (squeezeZone | bbExpanding | (bbWidth > _prev(bbWidth))) & (volRatio > ignitionVolMin) &
        (rsi > 43) & (rsi < 68) & (distanceFromEma21Atr < 3.0) & (ema21Slope >= 0) & (c > ema50))
    ignitionCore = ((squeezeZone & (volRatio > ignitionVolMin) & (rsi > 45) & (rsi < 64) &
                     (distanceFromEma21Atr < 2.5) & (ema21Slope > 0) & (c > ema50)) | fourHourExpansionSetup)
    premiumExpansion = ((atrPct > atrPctAvg * premiumAtrFactor) & (volRatio > premiumVolMin) &
                        (rsi >= premiumRsiMin) & (distanceFromEma21Atr >= premiumExtensionAtr) &
                        (c >= recentHigh - atr * 1.10) & (bbWidth > bbWidthAvg * 1.10))
    manageCore = (rsi > 74) & (distanceFromEma21Atr > 1.8) & (volRatio > 1.25) & (c < _prev(h))
    bottomContext = (c <= lowestClose40 + atr * 2.2) | (rsi < 55) | (c < ema200 * 1.05)
    structureWeak = (c < ema21) & (ema21Slope < 0)
    trendWeak = (c < ema50) | (ema21 < ema50)
    momentumWeak = (rsi < 45) & (rsi < _prev(rsi))
    effAccMinScore = max(40, accumulateMinScore - 6) if (isRelaxedTimeframe and relax4HSignals) else accumulateMinScore
    addCoreBase = ((campaignScore >= addMinScore) & (rsi > 52) & (rsi < 70) & (volRatio > addVolMin) &
                   (distanceFromEma21Atr < 2.8) & (c > ema50) & (ema21Slope > 0))
    nearRecentHigh = (recentHigh - c) <= atr * (1.55 if isRelaxedTimeframe else 1.25)
    extendedMomentum = (rsi > (63 if isRelaxedTimeframe else 66)) | (distanceFromEma21Atr > (1.15 if isRelaxedTimeframe else 1.35))
    rawSevereLowBreak = c < swingLow - atr * 0.35
    rawSevereTrendBreak = (c < ema50) & (ema21 < ema50) & (ema21Slope < 0)
    rawSevereMomentumBreak = (rsi < 40) & (rsi < _prev(rsi) - 3)
    rawSevereScoreBreak = campaignScore < 35
    protectedStructureBreak = (c < ema50) & (ema21 < ema50) & (ema21Slope < 0)

    # ---- stateful pass ----
    out = {k: np.zeros(n, dtype=bool) for k in
           ["STRONG START", "CAMPAIGN START", "FIRE ADD", "ACCUMULATE", "IGNITION", "ADD",
            "PREMIUM", "MANAGE", "PEAK", "FAIL (any severity)", "FAIL TEST", "RELOAD",
            "START TEST", "IGNITION TEST"]}
    # Stateful continuous series (Test 5A feature inventory §1.2). Recorded at
    # the same point in the bar the events are decided, so they carry exactly
    # the state Pine had when it made that bar's call.
    st = {k: np.full(n, np.nan) for k in
          ["campaignHealth", "campaignMaturityScore", "phaseConfidence",
           "weaknessCount", "campaignStrength"]}

    lastEventBar = lastIgnitionBar = lastAccumulateBar = lastAddBar = None
    lastPremiumBar = lastManageBar = campaignStartBar = lastPeakBar = failureLockBar = None
    campaignActive = False; weaknessCount = 0; campaignStrength = 0; campaignAddCount = 0
    reloadPrintedThisCampaign = False
    recoveryWatchActive = False; recoveryFailTestLevel = NA; recoveryHealthAtFail = NA
    recoveryStrengthAtFail = 0; recoveryFailBar = None; postFailReloadPrinted = False
    pendingType = 0; pendingBar = None; pendingExpiryBar = None
    pendingPrice = pendingLow = pendingHigh = pendingScore = pendingHealth = pendingRsi = pendingEmaSlope = NA
    pendingWasCampaignActive = False
    peakManageCount = peakSupportCount = 0; peakSequenceLastBar = None
    persistentHealth = 0.0; healthEmaState = NA; prevCampaignHealth = 0

    def since(b, i):
        return 100000 if b is None else i - b

    for i in range(n):
        if np.isnan(campaignScore[i]) or np.isnan(ema200[i]):
            continue
        eventReady = (lastEventBar is None) or (i - lastEventBar > signalCooldown)
        bsIgn, bsAcc, bsAdd = since(lastIgnitionBar, i), since(lastAccumulateBar, i), since(lastAddBar, i)
        bsPrem, bsMan, bsPeak = since(lastPremiumBar, i), since(lastManageBar, i), since(lastPeakBar, i)
        premiumActive = bsPrem <= premiumMemoryBars
        peakRecentlyPrinted = bsPeak <= peakWindowBars
        maturityWarningActive = premiumActive or peakRecentlyPrinted
        campaignKnown = campaignActive or (bsAcc <= memoryBars or bsIgn <= memoryBars or bsAdd <= memoryBars)

        continuationContext = (campaignKnown and c[i] > ema50[i] and ema21[i] > ema50[i]
                               and ema21Slope[i] > 0 and l[i] > recentLow[i])
        bottomOpportunity = (campaignScore[i] >= effAccMinScore and ignitionCore[i]
                             and bottomContext[i] and not premiumActive)
        campaignStartCandidate = eventReady and bottomOpportunity and not campaignActive
        accumulateEvent = (bottomOpportunity and campaignActive and
                           (lastAccumulateBar is None or i - lastAccumulateBar > accumulateCooldown))
        addCore = bool(addCoreBase[i]) and not premiumActive
        strongStartCandidate = campaignStartCandidate and addCore
        addCandidate = eventReady and addCore and continuationContext and not campaignStartCandidate
        ignitionCandidate = (eventReady and ignitionCore[i] and not campaignStartCandidate
                             and not accumulateEvent and not addCandidate)
        premiumCandidate = eventReady and premiumExpansion[i] and bsPrem > premiumCooldownBars
        manageCandidate = manageCore[i] and bsMan > manageCooldown

        campaignAgeCurrent = (i - campaignStartBar) if (campaignActive and campaignStartBar is not None) else 0
        ageScore = int(min(20.0, campaignAgeCurrent * 20.0 / max(1, ageMatureBars))) if campaignActive else 0
        strengthMaturityScore = int(min(35.0, campaignStrength * 35.0 / max(1, strengthMax)))
        addMaturityScore = int(min(25.0, campaignAddCount * 25.0 / max(1, peakMaturityAdds)))
        expansionMaturityScore = 10 if (campaignActive and c[i] > ema21[i] and ema21[i] > ema50[i] and ema21Slope[i] > 0) else 0
        extensionMaturityScore = 10 if (campaignActive and (distanceFromEma21Atr[i] > 1.15 or rsi[i] > 64)) else 0
        campaignMaturityScore = int(min(100, ageScore + strengthMaturityScore + addMaturityScore
                                        + expansionMaturityScore + extensionMaturityScore))

        # peak sequence counters
        if (peakSequenceLastBar is not None and i - peakSequenceLastBar > peakWindowBars) or not campaignActive:
            peakManageCount = peakSupportCount = 0; peakSequenceLastBar = None
        if campaignActive and manageCandidate:
            peakManageCount += 1; peakSequenceLastBar = i
        if campaignActive and (addCandidate or premiumCandidate):
            peakSupportCount += 1; peakSequenceLastBar = i

        peakSequenceReady = peakManageCount >= 2 and peakSupportCount >= 1
        campaignMature = (campaignMaturityScore >= maturityPeakScore or campaignStrength >= peakMaturityStrength
                          or campaignAddCount >= peakMaturityAdds)
        matureSequenceReady = campaignMature and campaignAddCount >= 2 and (peakManageCount >= 1 or premiumActive)
        postRunStall = (campaignMature and nearRecentHigh[i] and c[i] <= c[i - 1] if i else False) and \
                       (rsi[i] < rsi[i - 1] or ema21Slope[i] < ema21Slope[i - 1] if i else False)
        maturityPeakReady = (campaignMaturityScore >= maturityPeakScore and campaignAddCount >= 2 and nearRecentHigh[i]
                             and (manageCandidate or premiumActive or postRunStall)
                             and (rsi[i] > (61 if isRelaxedTimeframe else 64)
                                  or distanceFromEma21Atr[i] > (1.0 if isRelaxedTimeframe else 1.2)))
        peakCandidate = (campaignActive and bsPeak > peakCooldownBars and nearRecentHigh[i] and extendedMomentum[i]
                         and (peakSequenceReady or matureSequenceReady or postRunStall or maturityPeakReady))

        # health
        if campaignKnown and (structureWeak[i] or trendWeak[i] or momentumWeak[i]):
            weaknessCount += 1
        else:
            weaknessCount = max(0, weaknessCount - 1)
        healthPenalty = (8 if premiumActive else 0) + weaknessCount * 8 + (10 if manageCore[i] else 0)
        rawHealth = min(100.0, max(0.0, campaignScore[i] - healthPenalty + healthTolerance))
        a = 2.0 / (healthSmoothLen + 1)
        healthEmaState = rawHealth if np.isnan(healthEmaState) else a * rawHealth + (1 - a) * healthEmaState
        smoothed = healthEmaState
        stepUp = min(100.0, persistentHealth + 12.0)
        stepDown = max(0.0, persistentHealth - (5.0 if tf_hours <= 1 else 8.0))
        if campaignActive:
            persistentHealth = min(smoothed, stepUp) if smoothed > persistentHealth else max(smoothed, stepDown)
        else:
            persistentHealth = smoothed
        campaignHealth = int(round(persistentHealth))

        failureReady = (failureLockBar is None) or (i - failureLockBar > memoryBars)
        strengthProtection = min(20, campaignStrength * strengthFailProtection)
        protectedFailHealthLevel = max(12, healthFailTestLevel - strengthProtection)
        strongCampaignProtected = campaignStrength >= strongCampaignLevel and not (maturityWarningActive or postRunStall)
        requiredWeaknessBars = max(2, failureConfirmBars + (1 if strongCampaignProtected else 0) - (1 if maturityWarningActive else 0))
        requiredFailHealth = protectedFailHealthLevel if strongCampaignProtected else healthFailTestLevel
        failCandidate = (eventReady and failureReady and campaignKnown and weaknessCount >= requiredWeaknessBars
                         and campaignHealth <= requiredFailHealth
                         and (protectedStructureBreak[i] if strongCampaignProtected
                              else (c[i] < swingLow[i] or trendWeak[i])))
        resetEvent = campaignActive and c[i] < ema50[i] and ema21Slope[i] <= 0 and weaknessCount >= failureConfirmBars
        catastrophicFailCandidate = (eventReady and failureReady and campaignKnown
                                     and campaignHealth <= healthEmergencyLevel
                                     and rawSevereLowBreak[i] and rawSevereTrendBreak[i]
                                     and (rawSevereMomentumBreak[i] or rawSevereScoreBreak[i]))

        pendingActive = pendingType != 0
        barsIntoTest = (i - pendingBar) if pendingActive else 0
        startConflict = (not pendingActive) and failCandidate and (strongStartCandidate or campaignStartCandidate)
        ignitionConflict = (not pendingActive) and failCandidate and ignitionCandidate
        startTestEvent = startConflict
        ignitionTestEvent = ignitionConflict
        failTestEvent = ((not pendingActive) and failCandidate and not catastrophicFailCandidate
                         and not startConflict and not ignitionConflict)

        if startTestEvent or ignitionTestEvent or failTestEvent:
            pendingType = 1 if startTestEvent else 2 if ignitionTestEvent else 3
            pendingBar = i
            pendingExpiryBar = i + (reloadWindowBars if failTestEvent else resolutionBars)
            pendingPrice, pendingLow, pendingHigh = c[i], l[i], h[i]
            pendingScore, pendingHealth, pendingRsi = campaignScore[i], campaignHealth, rsi[i]
            pendingEmaSlope = ema21Slope[i]; pendingWasCampaignActive = campaignActive
            pendingActive = True; barsIntoTest = 0

        resolutionScore = 0
        if pendingActive:
            resolutionScore += 2 if campaignScore[i] >= pendingScore + 3 else 0
            resolutionScore += 1 if rsi[i] > pendingRsi else 0
            resolutionScore += 1 if ema21Slope[i] > pendingEmaSlope else 0
            resolutionScore += 1 if c[i] > pendingPrice else 0
            resolutionScore += 1 if l[i] >= pendingLow else 0
            resolutionScore += 1 if c[i] > ema21[i] else 0
            resolutionScore += 1 if (bbExpanding[i] and c[i] > bbBasis[i]) else 0
            resolutionScore -= 2 if campaignScore[i] <= pendingScore - 8 else 0
            resolutionScore -= 2 if rsi[i] <= pendingRsi - 5 else 0
            resolutionScore -= 3 if c[i] < pendingLow else 0
            resolutionScore -= 2 if c[i] < ema50[i] else 0

        normalResolutionReady = pendingActive and barsIntoTest >= resolutionMinBars
        testExpired = pendingActive and pendingExpiryBar is not None and i >= pendingExpiryBar
        severeLowBreak = pendingActive and c[i] < pendingLow - atr[i] * 0.35
        severeTrendBreak = pendingActive and c[i] < ema50[i] and ema21[i] < ema50[i] and ema21Slope[i] < 0
        severeMomentumBreak = pendingActive and rsi[i] <= pendingRsi - 8 and rsi[i] < 42
        severeScoreBreak = pendingActive and campaignScore[i] <= pendingScore - 14
        emergencyFail = (pendingActive and barsIntoTest >= 1 and severeLowBreak and severeTrendBreak
                         and (severeMomentumBreak or severeScoreBreak))
        bullResolution = normalResolutionReady and resolutionScore >= resolutionConfirmScore
        bearResolution = normalResolutionReady and resolutionScore <= resolutionFailScore

        reloadStructure = (pendingActive and c[i] > pendingPrice and c[i] > ema21[i]
                           and ema21Slope[i] >= pendingEmaSlope and l[i] > pendingLow)
        reloadMomentum = pendingActive and rsi[i] >= pendingRsi and campaignScore[i] >= pendingScore + reloadScoreRecovery
        reloadHealth = pendingActive and (campaignHealth >= pendingHealth + reloadHealthRecovery
                                          or campaignHealth >= healthFailTestLevel + 12)
        reloadVolume = volRatio[i] >= reloadMinVolume or (i > 0 and vol[i] > vol[i - 1])
        reloadCandidate = (pendingType == 3 and not reloadPrintedThisCampaign and normalResolutionReady
                           and barsIntoTest <= reloadWindowBars and reloadStructure and reloadMomentum
                           and reloadHealth and reloadVolume)
        failTestConfirmed = (pendingType == 3 and normalResolutionReady and campaignHealth <= healthFailTestLevel
                             and (bearResolution or c[i] < pendingLow or (trendWeak[i] and momentumWeak[i])))
        expiryBreakdown = testExpired and (c[i] < pendingLow or (trendWeak[i] and momentumWeak[i]))

        confirmedStartEvent = resolvedAddEvent = resolvedFailEvent = reloadEvent = testExpiredEvent = False
        if pendingType == 3:
            if emergencyFail or failTestConfirmed or expiryBreakdown:
                resolvedFailEvent = True
            elif reloadCandidate:
                reloadEvent = True
            elif testExpired:
                testExpiredEvent = True
        elif pendingType != 0:
            if bullResolution:
                if pendingType == 1:
                    confirmedStartEvent = True
                else:
                    resolvedAddEvent = pendingWasCampaignActive
                    confirmedStartEvent = not pendingWasCampaignActive
            elif emergencyFail or bearResolution or expiryBreakdown:
                resolvedFailEvent = True
            elif testExpired:
                testExpiredEvent = True
        testResolved = confirmedStartEvent or resolvedAddEvent or resolvedFailEvent or reloadEvent or testExpiredEvent

        if resolvedFailEvent and pendingType == 3:
            recoveryWatchActive = True; recoveryFailTestLevel = pendingPrice
            recoveryHealthAtFail = campaignHealth; recoveryStrengthAtFail = campaignStrength
            recoveryFailBar = i; postFailReloadPrinted = False
        if testResolved:
            pendingType = 0; pendingBar = pendingExpiryBar = None
            pendingPrice = pendingLow = pendingHigh = pendingScore = pendingHealth = pendingRsi = pendingEmaSlope = NA
            pendingWasCampaignActive = False
            pendingActive = False

        strongStartEvent = (not pendingActive) and (not startConflict) and strongStartCandidate
        campaignStartDecision = ((not pendingActive) and (not startConflict) and campaignStartCandidate
                                 and not strongStartCandidate)
        addEvent = resolvedAddEvent or ((not pendingActive) and (not ignitionConflict) and addCandidate)
        ignitionEvent = (not pendingActive) and (not ignitionConflict) and ignitionCandidate
        premiumEvent = (not pendingActive) and premiumCandidate
        peakEvent = (not pendingActive) and peakCandidate
        catastrophicFailEvent = (not pendingActive) and catastrophicFailCandidate
        failEvent = resolvedFailEvent or catastrophicFailEvent
        campaignStartEvent = confirmedStartEvent or campaignStartDecision

        recoveryBarsElapsed = (i - recoveryFailBar) if (recoveryWatchActive and recoveryFailBar is not None) else 100000
        recoveryWindowValid = recoveryWatchActive and 0 < recoveryBarsElapsed <= postFailRecoveryBars
        rLevel = recoveryWindowValid and not np.isnan(recoveryFailTestLevel) and c[i] > recoveryFailTestLevel
        rEma = recoveryWindowValid and c[i] > ema21[i]
        rTrend = recoveryWindowValid and ema21Slope[i] > 0
        rMom = recoveryWindowValid and i > 0 and rsi[i] > rsi[i - 1] and rsi[i] >= 48
        rHealth = recoveryWindowValid and not np.isnan(recoveryHealthAtFail) and campaignHealth >= recoveryHealthAtFail + postFailHealthRecovery
        rHigherLow = recoveryWindowValid and i > 0 and l[i] > recoveryLowestLow[i - 1]
        rStruct = recoveryWindowValid and c[i] > ema50[i] and ema21[i] >= ema50[i]
        rVol = recoveryWindowValid and (volRatio[i] >= 0.85 or (i > 0 and vol[i] > vol[i - 1]))
        postFailRecoveryScore = (30 * rLevel + 15 * rEma + 15 * rTrend + 10 * rMom + 15 * rHealth
                                 + 10 * rHigherLow + 5 * rStruct + 5 * rVol)
        recoveryConfirmationBar = (manageCandidate or addCandidate or ignitionCandidate
                                   or (i > 0 and c[i] > h[i - 1] and c[i] > ema21[i]))
        postFailReloadEvent = ((not pendingActive) and (not postFailReloadPrinted) and (not campaignStartEvent)
                               and (not strongStartEvent) and recoveryWindowValid and rLevel
                               and recoveryConfirmationBar and postFailRecoveryScore >= postFailRecoveryScoreMin)

        manageEvent = (not pendingActive) and manageCandidate and not postFailReloadEvent
        addEvent = addEvent and not postFailReloadEvent
        ignitionEvent = ignitionEvent and not postFailReloadEvent
        reloadDisplayEvent = reloadEvent or postFailReloadEvent

        if reloadEvent:
            campaignActive = True; weaknessCount = max(0, weaknessCount - 2); failureLockBar = None
            reloadPrintedThisCampaign = True; campaignStrength = min(strengthMax, max(1, campaignStrength))
        if postFailReloadEvent:
            campaignActive = True; weaknessCount = 0; failureLockBar = None
            reloadPrintedThisCampaign = True; postFailReloadPrinted = True; recoveryWatchActive = False
            campaignStrength = min(strengthMax, max(1, recoveryStrengthAtFail - 1))

        fireAddEvent = campaignActive and accumulateEvent and addEvent

        # ---- record stateful continuous series ----
        strengthPct = campaignStrength * 100.0 / strengthMax if strengthMax > 0 else 0.0
        rawPhaseConfidence = (campaignHealth * 0.42 + campaignScore[i] * 0.25
                              + campaignMaturityScore * 0.20 + strengthPct * 0.13
                              - weaknessCount * 2.0)
        st["campaignHealth"][i] = campaignHealth
        st["campaignMaturityScore"][i] = campaignMaturityScore
        st["phaseConfidence"][i] = int(round(max(0.0, min(100.0, rawPhaseConfidence))))
        st["weaknessCount"][i] = weaknessCount
        st["campaignStrength"][i] = campaignStrength

        # ---- record (mirrors the exported plot() expressions) ----
        out["STRONG START"][i] = strongStartEvent
        out["CAMPAIGN START"][i] = campaignStartEvent and not strongStartEvent
        out["FIRE ADD"][i] = fireAddEvent
        out["ACCUMULATE"][i] = accumulateEvent and not fireAddEvent
        out["IGNITION"][i] = ignitionEvent
        out["ADD"][i] = addEvent and not fireAddEvent
        out["PREMIUM"][i] = premiumEvent
        out["MANAGE"][i] = manageEvent
        out["PEAK"][i] = peakEvent
        out["FAIL (any severity)"][i] = failEvent
        out["FAIL TEST"][i] = failTestEvent
        out["RELOAD"][i] = reloadDisplayEvent
        out["START TEST"][i] = startTestEvent
        out["IGNITION TEST"][i] = ignitionTestEvent

        # ---- state updates ----
        if strongStartEvent or campaignStartEvent:
            campaignActive = True; campaignStartBar = i; lastAccumulateBar = i; lastEventBar = i
            campaignStrength = max(1, campaignStrength); campaignAddCount = 0
            reloadPrintedThisCampaign = False; recoveryWatchActive = False; postFailReloadPrinted = False
        if startTestEvent or ignitionTestEvent or failTestEvent:
            lastEventBar = i
        if reloadEvent:
            campaignActive = True; lastAccumulateBar = i; lastAddBar = i; lastEventBar = i
            if campaignStartBar is None:
                campaignStartBar = i
        if postFailReloadEvent:
            campaignActive = True; campaignStartBar = i; lastAccumulateBar = i
            lastAddBar = i; lastManageBar = i; lastEventBar = i
        if accumulateEvent:
            lastAccumulateBar = i; lastEventBar = i
        if ignitionEvent:
            lastIgnitionBar = i; lastEventBar = i
            if campaignStartBar is None:
                campaignStartBar = i
        if addEvent:
            lastAddBar = i; lastEventBar = i
            campaignStrength = min(strengthMax, max(1, campaignStrength) + 1); campaignAddCount += 1
        if premiumEvent:
            lastPremiumBar = i; lastEventBar = i; campaignStrength = max(0, campaignStrength - 2)
        if manageEvent:
            lastManageBar = i; lastEventBar = i
        if peakEvent:
            lastPeakBar = i; lastEventBar = i; campaignStrength = max(0, campaignStrength - 1)
            peakManageCount = peakSupportCount = 0; peakSequenceLastBar = None
        if failEvent:
            if catastrophicFailEvent and not resolvedFailEvent:
                recoveryWatchActive = False
            failureLockBar = i; lastEventBar = i; weaknessCount = 0
            campaignActive = False; campaignStartBar = None
            campaignStrength = 0; campaignAddCount = 0; reloadPrintedThisCampaign = False
        if resetEvent and not pendingActive and not reloadDisplayEvent:
            campaignActive = False; campaignStartBar = None
            campaignStrength = 0; campaignAddCount = 0; reloadPrintedThisCampaign = False
        if recoveryWatchActive and recoveryFailBar is not None and i - recoveryFailBar > postFailRecoveryBars:
            recoveryWatchActive = False

    res = pd.DataFrame(out)
    res.insert(0, "t_utc", df["t_utc"].values)
    # Indicator features (Test 5A inventory §1.1) + stateful series (§1.2).
    # Attached here so feature extraction and event replay can never drift
    # apart -- both come from one pass over the same state.
    feat = pd.DataFrame({
        "rsi": rsi, "ema21Slope": ema21Slope, "ema50Slope": ema50Slope,
        "volRatio": volRatio, "atrPct": atrPct,
        "atrPctRatio": np.where(atrPctAvg > 0, atrPct / atrPctAvg, np.nan),
        "bbWidth": bbWidth,
        "bbWidthRatio": np.where(bbWidthAvg > 0, bbWidth / bbWidthAvg, np.nan),
        "distanceFromEma21Atr": distanceFromEma21Atr,
        "pullbackFromHighPct": pullbackFromHighPct,
        "distEma50Atr": np.where(atr > 0, (c - ema50) / atr, np.nan),
        "distEma200Atr": np.where(atr > 0, (c - ema200) / atr, np.nan),
        "trendScore": trendScore.astype(float), "momentumScore": momentumScore.astype(float),
        "volumeScore": volumeScore.astype(float), "structureScore": structureScore.astype(float),
        "campaignScore": campaignScore,
    })
    for k, v in st.items():
        feat[k] = v
    return pd.concat([res, feat], axis=1)


FEATURES = [
    "rsi", "ema21Slope", "ema50Slope", "volRatio", "atrPct", "atrPctRatio",
    "bbWidth", "bbWidthRatio", "distanceFromEma21Atr", "pullbackFromHighPct",
    "distEma50Atr", "distEma200Atr", "trendScore", "momentumScore",
    "volumeScore", "structureScore", "campaignScore", "campaignHealth",
    "campaignMaturityScore", "phaseConfidence", "weaknessCount", "campaignStrength",
]
