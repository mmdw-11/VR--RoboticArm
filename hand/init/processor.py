
# processor.py
import numpy as np

class RadiusEstimator:
    def __init__(self):
        # 14个通道的特征向量参考图
        self.reference_map = {
            14: [1.26378, 5.5392, 5.65308, 8.702, 1.56567, 0.3567, 6.5405, 3.37275, 8.5016, 3.4816, 0.90067, 1.5272, 0.74157, 0.12243],
            # ... 其他半径数据保持不变 ...
            5: [10.43579, 36.39567, 20.37536, 34.04086, 5.67125, 8.75057, 22.8374, 7.51037, 29.24279, 12.81675, 3.94155, 11.85767, 7.53567, 1.82645]
        }
        self.weights = np.array([0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.radii = sorted(self.reference_map.keys(), reverse=True)
        self.ref_matrix = np.array([self.reference_map[r] for r in self.radii])

    def estimate_radius(self, input_data):
        """核心算法：计算加权欧式距离并线性插值"""
        input_vec = np.array(input_data)
        diff = self.ref_matrix - input_vec
        dist_sq = (diff ** 2) * self.weights
        distances = np.sqrt(np.sum(dist_sq, axis=1))

        nearest_idx = np.argsort(distances)[:2]
        idx1, idx2 = nearest_idx[0], nearest_idx[1]
        d1, d2 = distances[idx1], distances[idx2]
        r1, r2 = self.radii[idx1], self.radii[idx2]

        if d1 < 1e-5: return float(r1)
        total_dist = d1 + d2
        weight1, weight2 = d2 / total_dist, d1 / total_dist
        return round(r1 * weight1 + r2 * weight2, 2)