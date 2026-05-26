"use client"
import {LiveCtgCard} from '@/features/ctg/ui/live-ctg-card'
import {generateHistoryList} from '@/features/history/lib/mock'
import {HistoryCard} from '@/features/history/ui/history-card'
import {HistoryFilter} from '@/features/history/ui/history-filter'
import {HistoryToolbar} from '@/features/history/ui/history-toolbar'
import {Tabs, TabsContent, TabsList, TabsTrigger} from '@/shared/ui/tabs'
import Link from 'next/link'
import {Button} from '@/shared/ui/button'
import * as React from 'react'
import Image from "next/image";
import {UploadModal} from "@/features/upload/ui/upload-modal";
import {useEffect} from "react";
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

export default function Home() {
    const history = generateHistoryList(8)
    const {data} = useListMonitorsApiMonitorsGet()
    const activeMonitors: TMonitor[] = React.useMemo(() => {
        if (!data) return []
        const anyData: any = data as any
        if (Array.isArray(anyData?.active)) {
            return anyData.active.filter(Boolean)
        }
        if (Array.isArray(anyData)) {
            return anyData.map((m: any) => (typeof m === 'string' ? m : m?.id)).filter(Boolean)
        }
        return []
    }, [data]);

    const finishedMonitors: TMonitor[] = React.useMemo(() => {
        if (!data) return []
        const anyData: any = data as any
        if (Array.isArray(anyData?.finished)) {
            return anyData.finished.filter(Boolean)
        }
        if (Array.isArray(anyData)) {
            return anyData.map((m: any) => (typeof m === 'string' ? m : m?.id)).filter(Boolean)
        }
        return []
    }, [data]);

    const [open, setOpen] = React.useState(false)

    useEffect(() => {
        console.log('DATA: ', data)
    }, [data]);


    return (
        <main className="p-4 md:p-6 lg:p-8">
            <div className="flex items-center justify-between mb-4">
                <h1 className="text-xl font-semibold">Текущие роды</h1>
                <div className="text-muted-foreground text-sm">14:30</div>
            </div>

            <Tabs defaultValue="current" className="mb-6">
                <TabsList>
                    <TabsTrigger value="current">Текущие роды</TabsTrigger>
                    <TabsTrigger value="history">История</TabsTrigger>
                </TabsList>
                <TabsContent value="current">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {activeMonitors.length === 0 && finishedMonitors.length === 0 ? (
                            <div className="text-muted-foreground">Нет активных мониторов</div>
                        ) : (
                            activeMonitors.map((monitor, idx) => (
                                <LiveCtgCard key={monitor?.monitor_id} monitorId={monitor?.monitor_id || ''}
                                             staggerMs={idx * 120}/>
                            ))
                        )}
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {finishedMonitors.map((monitor, idx) => (
                                <LiveCtgCard key={monitor?.monitor_id} monitorId={monitor?.monitor_id || ''}
                                             staggerMs={idx * 120}/>
                        ))}
                    </div>
                    <button onClick={() => setOpen(true)}
                            className="md:col-span-2 fixed left-4 md:left-6 lg:left-8 bottom-16">
                        <Button variant={'bluest'} className="w-full h-12 text-xl rounded-2xl">
                            <Image width={17} height={20} src={'/ArrowRight.svg'} alt={'right'}/> Начать прием
                        </Button>
                    </button>
                    <UploadModal open={open} onOpenChange={setOpen}/>
                </TabsContent>
                <TabsContent value="review">
                    <div className="text-muted-foreground text-sm">Нет задач</div>
                </TabsContent>
                <TabsContent value="history">
                    <HistoryToolbar/>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                        {history.map(item => (
                            <HistoryCard key={item.id} item={item}/>
                        ))}
                    </div>
                    <HistoryFilter/>
                </TabsContent>
            </Tabs>
        </main>
    )
}
