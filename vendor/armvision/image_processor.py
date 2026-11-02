"""
基础图像处理器 - 完全复刻参考工程 draw_open_cv_feature_sketch
一步一图，每个中间步骤都返回BGR图像供保存
"""
import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

class ImageProcessor:
    def __init__(self, config=None):
        self.config = config or {}
        logger.debug("ImageProcessor initialized")

    def grayscale(self, image: np.ndarray) -> np.ndarray:
        """步骤1：灰度化"""
        b, g, r = cv2.split(image)
        gray = (0.2126 * r + 0.7152 * g + 0.0722 * b).astype(np.uint8)
        return gray

    def step_bilateral(self, gray: np.ndarray) -> np.ndarray:
        """步骤2：双边滤波平滑 - 优化参数以更好地保留边缘并减少噪声"""
        return cv2.bilateralFilter(gray, 9, 75, 75)

    def step_gaussian(self, smooth: np.ndarray) -> np.ndarray:
        """步骤3：高斯模糊提取细节 - 减少模糊程度"""
        return cv2.GaussianBlur(smooth, (3, 3), 0.6)

    def step_adaptive(self, detail: np.ndarray) -> np.ndarray:
        """步骤4：自适应阈值 - 优化参数以获得更好的线条"""
        return cv2.adaptiveThreshold(
            detail, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            19, 7,
        )

    def step_canny(self, detail: np.ndarray) -> np.ndarray:
        """步骤5：Canny边缘 - 调整阈值以捕获更多细节"""
        return cv2.Canny(detail, 35, 90)

    def step_fuse(self, thr: np.ndarray, canny: np.ndarray) -> np.ndarray:
        """步骤6：双线融合"""
        return cv2.bitwise_or(thr, canny)

    def step_roi_mask(self, gray: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
        """步骤7：生成人脸ROI掩码 - 优化检测参数和掩码范围"""
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.05, minNeighbors=4, minSize=(60, 60)
        )
        roi_mask = np.zeros((target_h, target_w), dtype=np.uint8)
        if len(faces) > 0:
            face_areas = faces[:, 2] * faces[:, 3]
            x, y, w, h = faces[int(np.argmax(face_areas))]
            center = (x + w // 2, y + int(h * 0.55))
            head_axes = (max(15, int(w * 0.85)), max(15, int(h * 1.2)))
            cv2.ellipse(roi_mask, center, head_axes, 0, 0, 360, 255, -1, cv2.LINE_AA)
            top = max(0, y - int(h * 0.1))
            bottom = min(target_h, y + int(h * 2.5))
            left = max(0, x - int(w * 0.9))
            right = min(target_w, x + int(w * 1.9))
            roi_mask[top:bottom, left:right] = 255
        else:
            roi_mask[:, :] = 255
        return roi_mask

    def step_roi_apply(self, lines: np.ndarray, roi_mask: np.ndarray) -> np.ndarray:
        """步骤8：应用ROI"""
        return cv2.bitwise_and(lines, roi_mask)

    def step_morphology(self, lines: np.ndarray) -> np.ndarray:
        """步骤9：形态学开闭 - 优化核大小和迭代次数以改善连接性"""
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        lines = cv2.morphologyEx(lines, cv2.MORPH_OPEN, kernel, iterations=1)
        lines = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, kernel, iterations=4)
        return lines

    def step_connected(self, lines: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
        """步骤10：连通域过滤 - 调整最小面积阈值以保留更多五官细节"""
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
        cleaned = np.zeros_like(lines)
        min_area = max(5, int(target_w * target_h * 0.000012))
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= min_area:
                cleaned[labels == i] = 255
        return cleaned

    def step_erode(self, cleaned: np.ndarray) -> np.ndarray:
        """步骤11：膨胀加粗线条 - 使用椭圆核"""
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        return cv2.dilate(cleaned, kernel, iterations=3)

    def step_connect_lines(self, lines: np.ndarray) -> np.ndarray:
        """步骤11.5：连接断线 - 使用形态学闭运算"""
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        lines = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, kernel, iterations=4)
        # 使用更大的核进行额外的连接
        kernel_large = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        lines = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, kernel_large, iterations=2)
        return lines

    def step_refine_lines(self, lines: np.ndarray) -> np.ndarray:
        """步骤11.6：细化线条 - 使用形态学细化"""
        # 使用椭圆核进行轻微细化
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        # 进行轻微腐蚀细化
        lines = cv2.erode(lines, kernel, iterations=1)
        return lines

    def step_invert(self, eroded: np.ndarray) -> np.ndarray:
        """步骤12：反色为白底黑线"""
        return cv2.bitwise_not(eroded)

    def portrait_lineart(self, gray: np.ndarray, output_size=(1024, 1024)) -> dict:
        """
        完整处理流程，返回每一步的BGR图像字典
        """
        target_w, target_h = output_size
        resized = cv2.resize(gray, (target_w, target_h), interpolation=cv2.INTER_AREA)

        smooth = self.step_bilateral(resized)
        detail = self.step_gaussian(smooth)
        thr = self.step_adaptive(detail)
        canny = self.step_canny(detail)
        fused = self.step_fuse(thr, canny)
        roi_mask = self.step_roi_mask(resized, target_h, target_w)
        roi_applied = self.step_roi_apply(fused, roi_mask)
        morphed = self.step_morphology(roi_applied)
        connected = self.step_connected(morphed, target_w, target_h)
        eroded = self.step_erode(connected)
        connected_lines = self.step_connect_lines(eroded)
        refined_lines = self.step_refine_lines(connected_lines)
        lineart = self.step_invert(refined_lines)

        return {
            "01_resized": cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR),
            "02_grayscale": cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR),
            "03_bilateral": cv2.cvtColor(smooth, cv2.COLOR_GRAY2BGR),
            "04_gaussian": cv2.cvtColor(detail, cv2.COLOR_GRAY2BGR),
            "05_adaptive": cv2.cvtColor(thr, cv2.COLOR_GRAY2BGR),
            "06_canny": cv2.cvtColor(canny, cv2.COLOR_GRAY2BGR),
            "07_fused": cv2.cvtColor(fused, cv2.COLOR_GRAY2BGR),
            "08_roi_mask": cv2.cvtColor(roi_mask, cv2.COLOR_GRAY2BGR),
            "09_roi_applied": cv2.cvtColor(roi_applied, cv2.COLOR_GRAY2BGR),
            "10_morphology": cv2.cvtColor(morphed, cv2.COLOR_GRAY2BGR),
            "11_connected": cv2.cvtColor(connected, cv2.COLOR_GRAY2BGR),
            "12_eroded": cv2.cvtColor(eroded, cv2.COLOR_GRAY2BGR),
            "13_lineart": cv2.cvtColor(lineart, cv2.COLOR_GRAY2BGR),
        }