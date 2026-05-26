"use client"

import * as React from "react"
import {CtgCard} from "@/features/ctg/ui/ctg-card"
import type {CtgPoint, CtgStatus} from "@/features/ctg/lib/mock"
import {generateCtgData} from "@/features/ctg/lib/mock"
import {
    connectStream,
    ensureIntervals,
    mergeMomentsByTime,
    FHR_BACKGROUND_COLORS,
    FHR_LINE_COLORS,
    TOCO_BACKGROUND_COLORS,
    TOCO_LINE_COLORS,
    type AnnotationIntervals,
    type Interval,
    type StreamMessage
} from "@/features/ctg/lib/streaming"
import {useState, startTransition} from "react";
import {Skeleton} from "@/shared/ui/skeleton";
import {
    useGetMonitorInfoApiMonitorsMonitorIdGet
} from "@/entities/generated/endpoints/ктг-мониторинг-api-v10-0-1-гц";

type Props = { monitorId: string; title?: string; room?: string; staggerMs?: number }

export function LiveCtgCard({monitorId, title = "Роды", room = "Кабинет", staggerMs = 0}: Props) {
    const [data, setData] = React.useState<CtgPoint[]>(() => [])
    const [status, setStatus] = React.useState<CtgStatus>('normal')
    const [loading, setLoading] = useState(false);
    const sampleMs = 1000
    const originSecRef = React.useRef<number | null>(null)
    const monitorInfo = useGetMonitorInfoApiMonitorsMonitorIdGet(monitorId);

    React.useEffect(() => {
        if (!monitorId) return

        let aborted = false
        const schedule = (cb: () => void) => {
            if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
                // @ts-ignore
                (window as any).requestIdleCallback(() => {
                    if (!aborted) cb()
                }, {timeout: 500})
            } else {
                setTimeout(() => {
                    if (!aborted) cb()
                }, Math.max(0, staggerMs))
            }
        }
        startTransition(() => setLoading(true))
        const start = () => connectStream(monitorId, (msg: StreamMessage) => {
            // дополнительная фильтрация по monitor_id на случай общих потоков
            // @ts-ignore
            if ((msg as any).monitor_id && (msg as any).monitor_id !== monitorId) return
            if (msg.kind === 'moments_batch') {
                startTransition(() => {
                    setData(prev => mergeMomentsByTime(prev as any, msg, originSecRef as any, sampleMs))
                })
                // обновление бейджа по warnings из батча, если есть
                const warns = (msg as any)?.warnings
                if (Array.isArray(warns) && warns.length > 0) {
                    startTransition(() => setStatus('acute'))
                }
            } else if (msg.kind === 'annotation') {
                const ann = msg as AnnotationIntervals
                const last = ensureIntervals(ann.fhr_line_status).at(-1)
                if (last) {
                    startTransition(() => {
                        if (last.color_id === 2 || last.color_id === 0) setStatus('acute')
                        else if (last.color_id === 1 || last.color_id === -1) setStatus('chronic')
                        else setStatus('normal')
                    })
                }
            }
        }, undefined, {throttleMs: 200}).finally(() => startTransition(() => setLoading(false)))
        const timer = setTimeout(() => schedule(() => {
            start()
        }), Math.max(0, staggerMs))
        return () => {
            aborted = true;
            clearTimeout(timer);
            start().then(c => c.abort())
        }
    }, [monitorId, staggerMs, monitorInfo.isPending, monitorInfo.data])

    return loading ? <Skeleton className={'w-64 h-32'}/> : (
        <CtgCard title={title} room={`${room} ${monitorId.slice(0, 4)}`} status={status} data={data}
                 monitorId={monitorId}
                 fhrSegments={[]}
                 fhrEventBands={[]}
        />
    )
}


