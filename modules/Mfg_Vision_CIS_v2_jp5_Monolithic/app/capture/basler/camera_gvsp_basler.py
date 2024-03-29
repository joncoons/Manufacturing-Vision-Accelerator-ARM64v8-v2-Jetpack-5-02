import os
import json
import sys
import time
import uuid
import requests
from io import BytesIO
from PIL import Image
from time import sleep
from typing import Any, Callable, Optional
import cv2
import numpy as np
from datetime import datetime
from pypylon import pylon
from pypylon import genicam
from capture.frame_preprocess import frame_resize
from capture.frame_save import FrameSave
from store.mysql_insert import InsertInference
from shapely.geometry import Polygon

class Basler_GVSP_Camera:

    def __init__(
        self, camID, camTrigger, camURI, camLocation, camPosition, camFPS, inferenceFPS, 
        modelAcvOD, modelAcvMultiClass, modelAcvMultiLabel, modelAcvOcr, modelAcvOcrUri, modelAcvOcrSecondary, 
        modelYolov5, modelFasterRCNN, modelRetinanet, modelMaskRCNN, modelClassMultiLabel, modelClassMultiClass, 
        modelName, modelVersion, targetDim, probThres, iouThres, retrainInterval, storeRawFrames, storeAllInferences, 
        modelFile, labelFile, send_to_upload: Callable[[str], None], send_to_upstream: Callable[[str], None]
        ):

        self.camID = camID
        self.camTrigger = camTrigger
        self.camURI = camURI
        self.camLocation = camLocation
        self.camPosition = camPosition
        self.camFPS = camFPS
        self.inferenceFPS = inferenceFPS
        self.modelAcvOcr = modelAcvOcr
        self.modelAcvOcrUri = modelAcvOcrUri
        self.modelAcvOcrSecondary = modelAcvOcrSecondary
        self.modelAcvOD = modelAcvOD
        self.modelAcvMultiClass = modelAcvMultiClass
        self.modelAcvMultiLabel = modelAcvMultiLabel
        self.modelYolov5 = modelYolov5
        self.modelFasterRCNN = modelFasterRCNN
        self.modelRetinanet = modelRetinanet
        self.modelMaskRCNN = modelMaskRCNN
        self.modelClassMultiLabel = modelClassMultiLabel
        self.modelClassMultiClass = modelClassMultiClass
        self.modelFile = modelFile
        self.labelFile = labelFile
        self.targetDim = targetDim
        self.probThres = probThres
        self.iouThres = iouThres
        self.retrainInterval = retrainInterval
        self.storeRawFrames = storeRawFrames
        self.storeAllInferences = storeAllInferences        
        self.SqlDb = os.environ["MYSQL_DATABASE"]
        self.SqlPwd = os.environ["MYSQL_PWD"]
        self.model_name = modelName
        self.model_version = modelVersion
        self.send_to_upload = send_to_upload
        self.send_to_upstream = send_to_upstream

        self.frameCount = 0
        self.frameRateCount = 0

        self.cycle_begin = 0
        self.cycle_end = 0
        self.t_full_cycle = 0

        self.work_boundary = [(0, 640), (0, 0), (220, 0), (220, 640)]

        global capturing
        self.capturing = False

        self.streamCap()

    def streamCap(self):
        while True:

            cam_info = pylon.DeviceInfo()
            cam_info.SetSerialNumber(self.camURI)
            camera = pylon.InstantCamera(pylon.TlFactory.GetInstance().CreateFirstDevice(cam_info))
            camera.open()

            # Grabing Continusely (video) with minimal delay
            camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly) 
            converter = pylon.ImageFormatConverter()

            # converting to opencv bgr format
            converter.OutputPixelFormat = pylon.PixelType_BGR8packed
            converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

            while camera.IsGrabbing():
                grabResult = camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)

                if grabResult.GrabSucceeded():

                    # Access the image data
                    print("SizeX: ", grabResult.Width)
                    print("SizeY: ", grabResult.Height)

                    image = converter.Convert(grabResult)
                    frame = image.GetArray()

                    if self.camTrigger:
                        pass
                    else:
                        if self.inferenceFPS > 0:
                            if self.frameRateCount == int(self.camFPS/self.inferenceFPS): 
                                self.frameRateCount = 0 
                                pass   

                    self.cycle_begin = time.time()

                    h, w = frame.shape[:2]                            
                    if self.modelAcvMultiClass:
                        from inference.ort_acv_mc_class import predict_acv_mc_class
                        model_type = 'Multi-Class Classification'
                        frame_optimized = frame_resize(frame, self.targetDim, model = "classification")
                        result = predict_acv_mc_class(frame_optimized)
                        predictions = result['predictions']
                        frame_resized = frame_optimized.copy()
                    elif self.modelAcvMultiLabel:
                        from inference.ort_acv_ml_class import predict_acv_ml_class
                        model_type = 'Multi-Class Classification'
                        frame_optimized = frame_resize(frame, self.targetDim, model = "classification")
                        result = predict_acv_ml_class(frame_optimized)
                        predictions = result['predictions']
                        frame_resized = frame_optimized.copy()
                    elif self.modelAcvOD:
                        model_type = 'Object Detection'
                        frame_optimized = frame_resize(frame, self.targetDim, model = "acv")
                        from inference.ort_acv_predict import predict_acv
                        pil_frame = Image.fromarray(frame_optimized)
                        result = predict_acv(pil_frame)
                        predictions = result['predictions']
                        frame_resized = frame_optimized.copy()
                        annotated_frame = frame_optimized.copy()
                    elif self.modelYolov5:
                        model_type = 'Object Detection'
                        frame_optimized, ratio, pad_list = frame_resize(frame, self.targetDim, model = "yolov5")
                        from inference.ort_yolov5 import predict_yolov5
                        result = predict_yolov5(frame_optimized, pad_list)
                        predictions = result['predictions'][0]
                        new_w = int(ratio[0]*w)
                        new_h = int(ratio[1]*h)
                        frame_resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                        annotated_frame = frame_resized.copy()
                    elif self.modelFasterRCNN:
                        model_type = 'Object Detection'
                        frame_optimized = frame_resize(frame, self.targetDim, model = "faster_rcnn")
                        from inference.ort_faster_rcnn import predict_faster_rcnn
                        result = predict_faster_rcnn(frame_optimized)
                        predictions = result['predictions']
                        frame_resized = frame_optimized.copy()
                        annotated_frame = frame_optimized.copy()
                    elif self.modelMaskRCNN:
                        from inference.ort_mask_rcnn import predict_mask_rcnn
                        model_type = 'Instance Segmentation'
                        frame_optimized, ratio, padding = frame_resize(frame, self.targetDim, model = "mask_rcnn")
                        result, annotated_frame = predict_mask_rcnn(frame_optimized)
                        predictions = result['predictions']
                        frame_resized = frame_optimized.copy()   
                    elif self.modelClassMultiLabel:
                        model_type = 'Multi-Label Classification'
                        frame_optimized = frame_resize(frame, self.targetDim, model = "classification")
                        from inference.ort_class_multi_label import predict_class_multi_label
                        result = predict_class_multi_label(frame_optimized)
                        predictions = result['predictions']
                        frame_resized = frame_optimized.copy()
                        annotated_frame = frame_optimized.copy()
                    elif self.modelClassMultiClass:
                        model_type = 'Multi-Class Classification'
                        frame_optimized = frame_resize(frame, self.targetDim, model = "classification")
                        from inference.ort_class_multi_class import predict_class_multi_class
                        result = predict_class_multi_class(frame_optimized)
                        predictions = result['predictions']
                        frame_resized = frame_optimized.copy()
                        annotated_frame = frame_optimized.copy()
                    else:
                        print("No model selected")
                        result = None

                    now = datetime.now()
                    created = now.isoformat()
                    unique_id = str(uuid.uuid4())
                    filetime = now.strftime("%Y%d%m%H%M%S%f")
                    annotatedName = f"{self.camLocation}-{self.camPosition}-{filetime}-annotated.jpg"
                    annotatedPath = os.path.join('/images_volume', annotatedName)
                    frameFileName = f"{self.camLocation}-{self.camPosition}-{filetime}-rawframe.jpg"
                    frameFilePath = os.path.join('/images_volume', frameFileName)
                    retrainFileName = f"{self.camLocation}-{self.camPosition}-{filetime}-retrain.jpg"
                    retrainFilePath = os.path.join('/images_volume', retrainFileName)
                    
                    if result is not None:
                        print(json.dumps(result, indent=1))

                    if predictions is not None:
                        detection_count = len(predictions)
                        t_infer = result["inference_time"]
                        print(f"Detection Count: {detection_count}")

                    if model_type == 'Object Detection':
                        # detection_count = len(result['predictions'][0])
                        # t_infer = result["inference_time"]
                        # print(f"Detection Count: {detection_count}")
                        if detection_count > 0:
                            inference_obj = {
                            'model_name': self.model_name,
                            'object_detected': 1,
                            'camera_id': self.camID,
                            'camera_name': f"{self.camLocation}-{self.camPosition}",
                            'raw_image_name': frameFileName,
                            'raw_image_local_path': frameFilePath,
                            'annotated_image_name': annotatedName,
                            'annotated_image_path': annotatedPath,
                            'inferencing_time': t_infer,
                            'created': created,
                            'unique_id': unique_id,
                            'detected_objects': predictions
                            }

                            # For establishing boundary area - comment out if not used
                            boundary_active = self.__convertStringToBool(os.environ['BOUNDARY_DETECTION'])
                            work_polygon = Polygon(self.work_boundary)
                            object_poly_list = []       

                            for i in range(detection_count):
                                bounding_box = predictions[i]['bbox']
                                tag_name = predictions[i]['labelName']
                                probability = round(predictions[i]['probability'],2)
                                
                                # /////////////////////////////////////
                                # Simple object detection bounding box
                                # 
                                # image_text = f"{probability}%"
                                # color = (0, 255, 0)
                                # thickness = 1
                                # if bounding_box:
                                #     if self.modelAcvOD:
                                #         height, width, channel = annotated_frame.shape
                                #         xmin = int(bounding_box["left"] * width)
                                #         xmax = int((bounding_box["left"] * width) + (bounding_box["width"] * width))
                                #         ymin = int(bounding_box["top"] * height)
                                #         ymax = int((bounding_box["top"] * height) + (bounding_box["height"] * height))
                                #     else:
                                #         xmin = int(bounding_box["left"])
                                #         xmax = int(bounding_box["width"])
                                #         ymin = int(bounding_box["top"])
                                #         ymax = int(bounding_box["height"])
                                #     start_point = (int(bounding_box["left"]), int(bounding_box["top"]))
                                #     end_point = (int(bounding_box["width"]), int(bounding_box["height"]))
                                #     annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color, thickness)
                                    # annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (255,0, 0))

                                # /////////////////////////////////////
                                # Simple workplace saftey PPE detection example code
                                # 
                                image_text = f"{probability}%"
                                color1 = (0, 0, 255)
                                color2 = (0, 255, 0)
                                thickness1 = 1
                                thickness2 = 1
                                if bounding_box:
                                    if self.modelAcvOD:
                                        height, width, channel = annotated_frame.shape
                                        xmin = int(bounding_box["left"] * width)
                                        xmax = int((bounding_box["left"] * width) + (bounding_box["width"] * width))
                                        ymin = int(bounding_box["top"] * height)
                                        ymax = int((bounding_box["top"] * height) + (bounding_box["height"] * height))
                                        start_point = (xmin, ymin)
                                        end_point = (xmax, ymax)
                                        if tag_name == "no_hardhat" or tag_name == "no_safety_vest":
                                            annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color1, thickness1)
                                            # annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,0,255))
                                        else:
                                            annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color2, thickness2)
                                            # annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,255,0))
                                    else:
                                        start_point = (int(bounding_box["left"]), int(bounding_box["top"]))
                                        end_point = (int(bounding_box["width"]), int(bounding_box["height"]))
                                        if tag_name == "no_hardhat" or tag_name == "no_safety_vest":
                                            annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color1, thickness1)
                                            # annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,0,255))
                                        else:
                                            annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color2, thickness2)
                                            # annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,255,0))
                                    
                                # /////////////////////////////////////
                                # Object Detection for PPE with Boundary Area Identification
                                #
                                # image_text = f"{probability}%"
                                # color1 = (0, 0, 255)
                                # color2 = (0, 255, 0)
                                # thickness1 = 1
                                # thickness2 = 1
                                # if bounding_box:
                                #     if self.modelAcvOD:
                                #         height, width, channel = annotated_frame.shape
                                #         xmin = int(bounding_box["left"] * width)
                                #         xmax = int((bounding_box["left"] * width) + (bounding_box["width"] * width))
                                #         ymin = int(bounding_box["top"] * height)
                                #         ymax = int((bounding_box["top"] * height) + (bounding_box["height"] * height))
                                #         start_point = (xmin, ymin)
                                #         end_point = (xmax, ymax)
                                #         if tag_name == "no_hardhat" or tag_name == "no_safety_vest":
                                #             annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color1, thickness1)
                                #             annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,0,255))
                                #         else:
                                #             annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color2, thickness2)
                                #             annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,255,0))
                                #     else:
                                #         if boundary_active:
                                #             poly_red = (0, 0, 255)
                                #             poly_yellow = (0, 255, 255)
                                #             poly_black = (0, 0, 0)
                                #             poly_white = (255, 255, 255)
                                #             point1 = (int(bounding_box["left"]), int(bounding_box["top"]))
                                #             point2 = (int(bounding_box["width"]), int(bounding_box["top"]))
                                #             point3 = (int(bounding_box["width"]), int(bounding_box["height"]))
                                #             point4 = (int(bounding_box["left"]), int(bounding_box["height"]))
                                #             object_boundary = [(point1),(point2), (point3), (point4)]
                                #             print("object_boundary: ", object_boundary)
                                #             object_polygon = Polygon(object_boundary)
                                #             if object_polygon.intersects(work_polygon):
                                #                 object_poly_list.append(object_boundary)
                                #             start_point = (int(bounding_box["left"]), int(bounding_box["top"]))
                                #             end_point = (int(bounding_box["width"]), int(bounding_box["height"]))
                                #             if tag_name == "no_hardhat" or tag_name == "no_safety_vest":
                                #                 annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color1, thickness1)
                                #                 # annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,0,255))
                                #             else:
                                #                 annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color2, thickness2)
                                #                 # annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,255,0))

                                #         else:
                                #             start_point = (int(bounding_box["left"]), int(bounding_box["top"]))
                                #             end_point = (int(bounding_box["width"]), int(bounding_box["height"]))
                                #             if tag_name == "no_hardhat" or tag_name == "no_safety_vest":
                                #                 annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color1, thickness1)
                                #                 annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,0,255))
                                #             else:
                                #                 annotated_frame = cv2.rectangle(annotated_frame, start_point, end_point, color2, thickness2)
                                #                 annotated_frame = cv2.putText(annotated_frame, image_text, start_point, fontFace = cv2.FONT_HERSHEY_TRIPLEX, fontScale = .4, color = (0,255,0))
                                # 
                            # Code for creating poligon overlay - comment out if not using boundary detection
                            # if len(object_poly_list) > 0:
                            #     cv2.polylines(annotated_frame, np.array([self.work_boundary]), False, poly_yellow, 3)
                            #     overlay = annotated_frame.copy()
                            #     poly_arr = np.array(object_poly_list)
                            #     print(f'Poly/NP Array: {poly_arr}')
                            #     # cv2.fillPoly(overlay, np.array([self.work_boundary]), poly_white)
                            #     cv2.fillPoly(overlay, poly_arr, poly_red)
                            #     alpha = 0.4
                            #     annotated_frame = cv2.addWeighted(overlay, alpha, annotated_frame, 1 - alpha, 0)
                        
                            FrameSave(annotatedPath, annotated_frame)
                            annotated_msg = {
                                'fs_name': "images-annotated",
                                'img_name': annotatedName,
                                'location': self.camLocation,
                                'position': self.camPosition,
                                'path': annotatedPath
                                }
                            self.send_to_upload(json.dumps(annotated_msg))

                        elif detection_count==0 and self.storeAllInferences:
                            inference_obj = {
                                'model_name': self.model_name,
                                'object_detected': 0,
                                'camera_id': self.camID,
                                'camera_name': f"{self.camLocation}-{self.camPosition}",
                                'raw_image_name': frameFileName,
                                'raw_image_local_path': frameFilePath,
                                'annotated_image_name': frameFileName,
                                'annotated_image_path': frameFilePath,
                                'inferencing_time': t_infer,
                                'created': created,
                                'unique_id': unique_id,
                                'detected_objects': predictions
                                }

                        sql_insert = InsertInference(self.SqlDb, self.SqlPwd, detection_count, inference_obj)           
                        self.send_to_upstream(json.dumps(inference_obj)) 

                    elif model_type == 'Instance Segmentation':
                        t_infer = result["inference_time"]
                        if detection_count > 0:
                            print(f"Detection Count: {detection_count}")
                            inference_obj = {
                            'model_name': self.model_name,
                            'object_detected': 1,
                            'camera_id': self.camID,
                            'camera_name': f"{self.camLocation}-{self.camPosition}",
                            'raw_image_name': frameFileName,
                            'raw_image_local_path': frameFilePath,
                            'annotated_image_name': annotatedName,
                            'annotated_image_path': annotatedPath,
                            'inferencing_time': t_infer,
                            'created': created,
                            'unique_id': unique_id,
                            'detected_objects': predictions
                            }
                            
                            FrameSave(annotatedPath, annotated_frame)
                            
                            annotated_msg = {
                            'fs_name': "images-annotated",
                            'img_name': annotatedName,
                            'location': self.camLocation,
                            'position': self.camPosition,
                            'path': annotatedPath
                            }
                            self.send_to_upload(json.dumps(annotated_msg))  

                        elif detection_count==0 and self.storeAllInferences:
                            print("No object detected.")
                            inference_obj = {
                                'model_name': self.model_name,
                                'object_detected': 0,
                                'camera_id': self.camID,
                                'camera_name': f"{self.camLocation}-{self.camPosition}",
                                'raw_image_name': frameFileName,
                                'raw_image_local_path': frameFilePath,
                                'annotated_image_name': frameFileName,
                                'annotated_image_path': frameFilePath,
                                'inferencing_time': t_infer,
                                'created': created,
                                'unique_id': unique_id,
                                'detected_objects': predictions
                                }

                        sql_insert = InsertInference(self.SqlDb, self.SqlPwd, detection_count, inference_obj)           
                        self.send_to_upstream(json.dumps(inference_obj))              
                    
                    elif model_type == 'Multi-Label Classification' or model_type == 'Multi-Label Classification':
                        t_infer = result["inference_time"]
                        if detection_count > 0:
                            inference_obj = {
                            'model_name': self.model_name,
                            'object_detected': 1,
                            'camera_id': self.camID,
                            'camera_name': f"{self.camLocation}-{self.camPosition}",
                            'raw_image_name': frameFileName,
                            'raw_image_local_path': frameFilePath,
                            'annotated_image_name': frameFileName,
                            'annotated_image_path': frameFilePath,
                            'inferencing_time': t_infer,
                            'created': created,
                            'unique_id': unique_id,
                            'detected_objects': predictions
                            }

                        elif detection_count==0 and self.storeAllInferences:
                            print("No class detected.")
                            inference_obj = {
                                'model_name': self.model_name,
                                'object_detected': 0,
                                'camera_id': self.camID,
                                'camera_name': f"{self.camLocation}-{self.camPosition}",
                                'raw_image_name': frameFileName,
                                'raw_image_local_path': frameFilePath,
                                'annotated_image_name': frameFileName,
                                'annotated_image_path': frameFilePath,
                                'inferencing_time': t_infer,
                                'created': created,
                                'unique_id': unique_id,
                                'detected_objects': predictions
                                }

                        sql_insert = InsertInference(self.SqlDb, self.SqlPwd, detection_count, inference_obj)           
                        self.send_to_upstream(json.dumps(inference_obj))

                    print(f"Frame count = {self.frameCount}")

                    FrameSave(frameFilePath, frame_optimized)

                    if detection_count == 0 and self.storeRawFrames:
                        frame_msg = {
                        'fs_name': "images-frame",
                        'img_name': frameFileName,
                        'location': self.camLocation,
                        'position': self.camPosition,
                        'path': frameFilePath
                        }
                        self.send_to_upload(json.dumps(frame_msg))

                    if (self.frameCount*(self.inferenceFPS/self.camFPS)) % self.retrainInterval == 0:
                        FrameSave(retrainFilePath, frame)
                        retrain_msg = {
                        'fs_name': "images-retraining",
                        'img_name': retrainFileName,
                        'location': self.camLocation,
                        'position': self.camPosition,
                        'path': retrainFilePath
                        }
                        self.send_to_upload(json.dumps(retrain_msg))
                
                self.cycle_end = time.time()
                self.t_full_cycle = (self.cycle_end - self.cycle_begin)*1000
                print("Cycle Time in ms: {}".format(self.t_full_cycle))

    def __convertStringToBool(self, env: str) -> bool:
        if env in ['true', 'True', 'TRUE', '1', 'y', 'YES', 'Y', 'Yes']:
            return True
        elif env in ['false', 'False', 'FALSE', '0', 'n', 'NO', 'N', 'No']:
            return False
        else:
            raise ValueError('Could not convert string to bool.')