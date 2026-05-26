"use client"
import {HistoryFilter} from '@/features/history/ui/history-filter'
import {Button} from '@/shared/ui/button'
import Image from "next/image";
import {UploadModal} from "@/features/upload/ui/upload-modal"
import * as React from "react"
import {useEffect} from "react"
import {LiveCtgCard} from '@/features/ctg/ui/live-ctg-card'
import {
    useListMonitorsApiMonitorsGet
} from "@/entities/generated/endpoints/ктг-мониторинг-api-v10-0-1-гц";

type TMonitor = Partial<{
    monitor_id: string,
    created_at: string,
    speed: number,
    current_subscribers: number,
    total_subscribers_ever: number,
    current_time: number,
    total_duration: number,
    progress_percent: number
}>;

export default function KtgScreen() {
    const [open, setOpen] = React.useState(false)
    const {data, isSuccess} = useListMonitorsApiMonitorsGet()
    const monitors: TMonitor[] = React.useMemo(() => {
        const anyData: any = data as any
        if (Array.isArray(anyData?.active)) return anyData.active
        if (Array.isArray(anyData)) return anyData
        return []
    }, [data])
    useEffect(() => {
        console.log('sad')
        console.log(isSuccess, data)
    }, [data, isSuccess]);

    return (
        <main className="p-4 md:p-6 lg:p-8">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {monitors.map(monitor => {
                    console.log('mnt: ', monitor);
                    return (
                        <LiveCtgCard key={monitor.monitor_id} monitorId={monitor.monitor_id || ''}/>
                    )
                })}
            </div>
            <Button onClick={() => setOpen(true)} variant={'bluest'} className="w-full h-12 text-xl rounded-2xl">
                <Image width={17} height={20} src={'/ArrowRight.svg'} alt={'right'}/> Начать прием
            </Button>
            <HistoryFilter/>
            <UploadModal open={open} onOpenChange={setOpen}/>
        </main>
    )
}
