# 数据表初始化

本版通过 `src.models.base.Base.metadata.create_all` 创建首次运行所需的表：观测、签认补录、分析任务、复核、抽查队列与逐卡结果、分发计划、投递与审计。模型在 `src/models/workflow.py`。`python -m scripts.seed_demo` 按观测内容键补全演示样本，保留现有分析、签认及队列。数据库端口只发布到本机。
