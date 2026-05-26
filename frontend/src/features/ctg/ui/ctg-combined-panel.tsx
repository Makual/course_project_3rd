"use client"

import * as React from "react"
import {Area, CartesianGrid, ComposedChart, ReferenceArea, ReferenceLine, XAxis, YAxis} from "recharts"
import {D3CTG} from "@/shared/ui/d3-ctg"
import type {CtgPoint} from "@/features/ctg/lib/mock"
import {Badge} from "@/shared/ui/badge"
import {Tooltip, TooltipContent, TooltipTrigger} from "@/shared/ui/tooltip"

import {Card, CardContent} from "@/shared/ui/card"
import {ChartContainer} from "@/shared/ui/chart"
import {cn} from "@/shared/lib/css"

type Segment = { start: number; end: number; type: "accel" | "decel" }
type Band = { start: number; end: number; color: string; opacity?: number }

type Props = {
    disableDopInfo?: boolean
    data: CtgPoint[]
    lineKey: keyof CtgPoint
    color: string
    value?: number
    valueTitle?: string
    status?: "normal" | "chronic" | "acute" | ''
    badgeText?: string[]
    className?: string
    startTime?: Date
    sampleMs?: number
    yDomain?: [number, number]
    bands?: Band[]
    eventBands?: Band[]
    name?: string
    thresholdsY?: number[]
    animate?: boolean
    useD3?: boolean
    d3LineSegments?: { start: number; end: number; color: string }[]
    legendItems?: { label: string; color: string; kind?: 'line' | 'bg' }[]
}

function detectSegments(points: CtgPoint[], key: keyof CtgPoint): Segment[] {
    const segments: Segment[] = []
    // более чувствительные пороги, чтобы полосы были заметны на демо-данных
    const thresholdUp = 4
    const thresholdDown = -4
    let active: Segment | null = null

    for (let i = 3; i < points.length; i++) {
        const prev = points[i - 3][key] as number
        const curr = points[i][key] as number
        const delta = curr - prev
        const type = delta > thresholdUp ? ("accel" as const) : delta < thresholdDown ? ("decel" as const) : null

        if (type) {
            if (!active) {
                active = {start: points[i - 3].index, end: points[i].index, type}
            } else if (active.type === type) {
                active.end = points[i].index
            } else {
                if (active.end - active.start >= 3) segments.push(active)
                active = {start: points[i - 3].index, end: points[i].index, type}
            }
        } else if (active) {
            if (active.end - active.start >= 3) segments.push(active)
            active = null
        }
    }
    if (active && active.end - active.start >= 3) segments.push(active)
    return segments
}

/**
 * Combined CTG panel with a line chart and highlighted acceleration/deceleration bands.
 *
 * Features:
 * - Draws a smooth line (`Area`) for the provided series (`lineKey`) with configurable color
 * - Detects short-time trend segments (accelerations/decelerations) and overlays them
 *   as translucent rectangles across the full Y range
 * - Time is shown on the X axis. If `startTime` is not provided, it is inferred so the
 *   last point corresponds to the current time. The tick label formatter respects `sampleMs`.
 * - Optional right-side info column (status badge and last values) that can be hidden
 *   with `disableDopInfo`
 *
 * Accessibility: tooltips are kept for screen-reader hints and hover details.
 *
 * @param data Data points of the CTG series
 * @param disableDopInfo Hide the right-side info column if true
 * @param lineKey Key of the numeric field to render from each point
 * @param color Color of the line and its fill
 * @param value Optional numeric value to display in the info column
 * @param valueTitle Optional label for the numeric value in the info column
 * @param status Status used to color the badge: "normal" | "chronic" | "acute"
 * @param className Optional className for the root Card
 * @param startTime Start time for the X axis. If omitted, derived from now - data.length*sampleMs
 * @param sampleMs Sampling interval in milliseconds between points (default 60_000)
 * @param yDomain Explicit Y-axis domain [min, max]. Defaults to automatic domain
 */
export function CtgCombinedPanel({
                                     data,
                                     name,
                                     disableDopInfo = false,
                                     lineKey,
                                     color,
                                     value,
                                     valueTitle,
                                     status = '',
                                     badgeText,
                                     className,
                                     startTime,
                                     sampleMs = 60_000,
                                     yDomain,
                                     bands = [],
                                     eventBands = [],
                                     thresholdsY = [],
                                     animate = true,
                                     useD3 = false,
                                     d3LineSegments = [],
                                     legendItems = []
                                 }: Props) {
    const badgeClass = {
        normal: "bg-emerald-600/20 text-emerald-400 border-emerald-500/20",
        chronic: "bg-amber-500/20 text-amber-400 border-amber-500/20",
        acute: "bg-red-600/20 text-red-400 border-red-500/20",
        '': 'opacity-0'
    }[status]

    const segments = React.useMemo(() => detectSegments(data, lineKey), [data, lineKey])

    const base = React.useMemo(() => startTime ?? new Date(Date.now() - data.length * sampleMs), [startTime, data.length, sampleMs])
    const useRealTime = data.length > 0 && typeof (data[0] as any).rt === 'string'
    const formatTime = (idx: number) => {
        if (useRealTime) return String((data[idx] as any)?.rt ?? '')
        const t = new Date(base.getTime() + idx * sampleMs)
        const hh = String(t.getHours()).padStart(2, '0')
        const mm = String(t.getMinutes()).padStart(2, '0')
        return `${hh}:${mm}`
    }

    return (
        <Card className={cn("border-input p-0", className)}>
            <CardContent className="p-0 flex">
                <div className="flex-1 min-w-0">
                    <ChartContainer className="h-[230px] rounded-l-xl w-full" config={{[String(lineKey)]: {color}}}>
                        {useD3 ? (
                            <D3CTG name={name} data={data as any} yDomain={(yDomain as any) ?? ["auto", "auto"]}
                                   bands={bands as any} eventBands={eventBands as any} color={color}
                                   valueKey={lineKey as any} lineSegments={d3LineSegments as any}
                                   thresholdsY={thresholdsY} />
                        ) : (
                            <ComposedChart data={data} margin={{top: 8, right: 8, left: 0, bottom: 20}}>
                                <CartesianGrid strokeDasharray="3 3" vertical={false} strokeOpacity={0.2}/>
                                {useRealTime ? (
                                    <XAxis dataKey="rt" type="category" interval={"preserveStartEnd"} minTickGap={24}
                                           tick={{fill: "currentColor", opacity: 0.6}} tickLine={false}
                                           axisLine={false}/>
                                ) : (
                                    <XAxis dataKey="index" tickFormatter={(v) => formatTime(Number(v))}
                                           tick={{fill: "currentColor", opacity: 0.6}} tickLine={false}
                                           axisLine={false}/>
                                )}
                                <YAxis domain={yDomain ?? ["auto", "auto"]} tick={{fill: "currentColor", opacity: 0.6}}
                                       width={28}/>
                                {bands.map((b, idx) => (
                                    <ReferenceArea key={idx} x1={b.start} x2={b.end} fill={b.color}
                                                   fillOpacity={b.opacity ?? 0.18} strokeOpacity={0}/>
                                ))}
                                {eventBands.map((b, idx) => (
                                    <ReferenceArea key={`ev-${idx}`} x1={b.start} x2={b.end} fill={b.color}
                                                   fillOpacity={b.opacity ?? 0.16} strokeOpacity={0}/>
                                ))}
                                {thresholdsY.map((y, idx) => (
                                    <ReferenceLine key={`th-${idx}`} y={y} stroke="currentColor" strokeDasharray="4 4"
                                                   strokeOpacity={0.35}/>
                                ))}
                                <Area type="monotone" name={name} dataKey={String(lineKey)} stroke={color} fill={color}
                                      fillOpacity={0.08} strokeWidth={2} isAnimationActive={animate}/>
                                <Tooltip/>
                            </ComposedChart>
                        )}
                    </ChartContainer>
                    {legendItems.length > 0 && (
                        <div className="px-2 pt-2 flex flex-wrap gap-3 text-xs text-muted-foreground pb-4">
                            {legendItems.map((it, idx) => (
                                <div key={idx} className="flex items-center gap-2">
                                    <span className="inline-block w-3 h-3 rounded-sm" style={{
                                        backgroundColor: it.color,
                                        opacity: it.kind === 'bg' ? 0.35 : 1,
                                        outline: it.kind === 'bg' ? '1px dashed currentColor' : 'none'
                                    }}/>
                                    <span className="leading-none">{it.label}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {!disableDopInfo && <div
                    className="w-56 shrink-0 px-4 py-4 flex flex-col justify-between items-end border-l border-input rounded-r-xl">
                    {badgeText && badgeText.map(badge =>
                        <React.Fragment key={badge}>
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Badge
                                        className={cn("p-2 h-10 whitespace-normal break-words text-right w-full", badgeClass)}>
                                        {badge}
                                    </Badge>
                                </TooltipTrigger>
                                <TooltipContent>
                                    <p>{badge}</p>
                                </TooltipContent>
                            </Tooltip>
                        </React.Fragment>)}
                    <div className="text-right space-y-2">
                        <div className="text-md font-semibold text-muted-foreground">{valueTitle}</div>
                        <div className="text-6xl font-semibold tabular-nums leading-none">{value}</div>
                    </div>
                </div>}
            </CardContent>
        </Card>
    )
}


