# RKHS 与 MMD 的讨论（Exporter 样例）

###### You
为什么要用 RKHS？先看这张图：![plot](assets/plot.png)

###### ChatGPT
因为再生核希尔伯特空间可以让内积计算等价于核函数求值，无需显式构造特征映射。

###### You
那 MMD 又是怎么推出来的？

###### ChatGPT
MMD 是 RKHS 中两个分布嵌入之差的范数，平方展开后恰好只依赖核函数在两分布上的期望。
